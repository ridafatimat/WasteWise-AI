"""Groq-powered recipe research and natural-language meal planning.

The meal-planning flow is deliberately dynamic: no dish whitelist or hardcoded
recipe catalogue is used. Groq Compound researches the requested recipe with
web search, then a second Groq model converts the research into validated JSON
that the grocery engine can safely merge with pantry stock.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from difflib import SequenceMatcher
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError


class MealPlanParseError(ValueError):
    """Raised when a meal request cannot be converted into safe structured data."""


class GroqRequestTooLargeError(MealPlanParseError):
    """Raised when Groq rejects an oversized request payload."""


class ParsedIngredient(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    quantity: float = Field(gt=0, le=100000)
    unit: Literal["g", "kg", "ml", "l", "piece", "pack"]
    category: Literal[
        "beverage",
        "dairy",
        "fruit",
        "grain",
        "meat",
        "snack",
        "vegetable",
        "other",
    ] = "other"


class ParsedMeal(BaseModel):
    dish_name: str = Field(min_length=1, max_length=160)
    servings: int = Field(default=4, ge=1, le=30)
    times: int = Field(default=1, ge=1, le=14)
    ingredients: list[ParsedIngredient] = Field(min_length=1, max_length=60)
    assumptions: list[str] = Field(default_factory=list, max_length=12)


def _require_api_key() -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise MealPlanParseError(
            "GROQ_API_KEY is not configured. Add it to use AI meal planning."
        )
    return api_key


def _timeout_seconds() -> float:
    raw_value = os.getenv("GROQ_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise MealPlanParseError("GROQ_TIMEOUT_SECONDS must be a number.") from exc
    return max(5.0, min(value, 90.0))


async def _post_groq(
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    latest_compound_version: bool = False,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if latest_compound_version:
        headers["Groq-Model-Version"] = "latest"

    try:
        # Controlled timeout simulation for production-readiness testing.
        # When enabled, wait for the configured timeout period and then raise
        # the same HTTP timeout exception handled for a real Groq timeout.
        if os.getenv(
            "SIMULATE_GROQ_TIMEOUT",
            "false",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            await asyncio.sleep(timeout_seconds)
            raise httpx.ReadTimeout(
                "Simulated Groq timeout.",
                request=httpx.Request(
                    "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                ),
            )

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise MealPlanParseError("Groq took too long to research the recipe.") from exc
    except httpx.HTTPStatusError as exc:
        detail = "Groq could not process the meal request."
        api_message = ""

        try:
            error_payload = exc.response.json()
            api_message = str(
                error_payload.get("error", {}).get("message") or ""
            ).strip()
            if api_message:
                detail = f"Groq request failed: {api_message}"
        except Exception:
            pass

        if (
            exc.response.status_code == 413
            or "request entity too large" in api_message.lower()
            or "payload too large" in api_message.lower()
        ):
            raise GroqRequestTooLargeError(
                "Groq rejected an oversized recipe-research payload."
            ) from exc

        raise MealPlanParseError(detail) from exc
    except httpx.HTTPError as exc:
        raise MealPlanParseError("Groq is currently unavailable.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise MealPlanParseError("Groq returned an unreadable response.") from exc

    if not isinstance(data, dict):
        raise MealPlanParseError("Groq returned an invalid response.")
    return data


def _response_content(response_payload: dict[str, Any]) -> str:
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MealPlanParseError("Groq returned an incomplete response.") from exc

    if not isinstance(content, str) or not content.strip():
        raise MealPlanParseError("Groq returned an empty response.")
    return content.strip()


def _executed_web_search(response_payload: dict[str, Any]) -> bool:
    try:
        executed_tools = response_payload["choices"][0]["message"].get(
            "executed_tools", []
        )
    except (KeyError, IndexError, TypeError):
        return False

    serialized = json.dumps(executed_tools, default=str).lower()
    return "web_search" in serialized or "search_results" in serialized


def _collect_source_urls(value: Any, output: list[str]) -> None:
    if len(output) >= 8:
        return

    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(nested, str) and key.lower() in {"url", "source_url", "link"}:
                candidate = nested.strip()
                if candidate.startswith(("http://", "https://")) and candidate not in output:
                    output.append(candidate)
            else:
                _collect_source_urls(nested, output)
    elif isinstance(value, list):
        for nested in value:
            _collect_source_urls(nested, output)


def _source_urls(response_payload: dict[str, Any]) -> list[str]:
    output: list[str] = []
    try:
        executed_tools = response_payload["choices"][0]["message"].get(
            "executed_tools", []
        )
    except (KeyError, IndexError, TypeError):
        return output
    _collect_source_urls(executed_tools, output)
    return output


async def _research_recipe(
    message: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> tuple[str, bool, list[str]]:
    model = os.getenv("GROQ_RECIPE_RESEARCH_MODEL", "groq/compound-mini").strip()

    research_prompt = f"""You are researching a recipe for a household grocery-list application.

The user's exact meal plan is:
{message}

Interpret the requested dish literally. Preserve every explicitly named food
that functions as an ingredient or recipe base, and do not silently replace the
requested dish with a different preparation. When the wording is ambiguous,
choose the most direct everyday interpretation and record the assumption.

You MUST use web search before answering. Research a representative, practical
recipe for the requested dish. Infer servings and cooking frequency from the
message; use 4 servings and one cooking occurrence only when missing.

Return a concise COMPLETE research result. Prefer a single JSON object with:
- dish_name
- servings
- times
- ingredients: an array for ONE cooking occurrence, where each item contains
  product_name, quantity, and unit
- assumptions

If strict JSON is not possible, return the same information as a clearly
labelled concise brief.

The ingredient list must include every normal grocery ingredient needed to make
the dish, including its main protein or base, vegetables, aromatics, cooking
fat, spices, seasoning, and garnish where they are normally part of the recipe.
Do not return only a few representative ingredients. Do not omit an ingredient
because it may already exist in the user's pantry; the backend will subtract
pantry stock later.

Use generic grocery names rather than brands. Exclude only water. Convert
teaspoons, tablespoons, and cups into approximate grams or millilitres where
practical. Keep the research brief concise, but keep the ingredient list
complete."""

    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": research_prompt}],
    }

    if model.startswith("groq/compound"):
        payload["compound_custom"] = {
            "tools": {
                "enabled_tools": ["web_search"],
            }
        }

    response_payload = await _post_groq(
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
        latest_compound_version=model.startswith("groq/compound"),
    )
    return (
        _response_content(response_payload),
        _executed_web_search(response_payload),
        _source_urls(response_payload),
    )


async def _structure_recipe(
    message: str,
    research: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> ParsedMeal:
    model = os.getenv(
        "GROQ_STRUCTURED_MODEL",
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    ).strip()

    system_prompt = """Convert recipe research into JSON for a grocery-list application.
Return only one JSON object with these exact keys:
- dish_name: concise dish name
- servings: integer 1-30; use 4 only when genuinely missing
- times: integer 1-14; how many times the dish will be cooked; use 1 only when missing
- ingredients: array for ONE cooking occurrence at the stated servings. Each item must have product_name, quantity, unit, category.
- assumptions: array of short strings explaining defaults or interpretations

Allowed units: g, kg, ml, l, piece, pack.
Allowed categories: beverage, dairy, fruit, grain, meat, snack, vegetable, other.
Use generic ingredient names, not brands. Exclude only water. Merge duplicate ingredients.
Convert spoon/cup measures into practical grams or millilitres. Never return zero or negative quantities.

The ingredients array must represent the COMPLETE recipe, not merely the most
important ingredients or only ingredients believed to be missing from a pantry.
It must preserve foods explicitly named by the user whenever they function as
ingredients or recipe bases. Do not silently reinterpret the requested dish as
a different preparation. Include the dish's main protein or base, vegetables,
aromatics, cooking fat, spices, seasoning, and garnish when they are normally
required. Preserve every valid ingredient found in the research result."""

    compact_research = _compact_research(research)

    user_prompt = f"""Original user request:
{message}

Web-researched recipe brief:
{compact_research}

Produce the required JSON now."""

    payload = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        response_payload = await _post_groq(
            api_key=api_key,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
    except GroqRequestTooLargeError:
        # Retry once with a much smaller research brief. This preserves the
        # normal two-model flow while handling unusually verbose web results.
        compact_research = _compact_research(research, max_characters=4500)
        payload["messages"][1]["content"] = f"""Original user request:
{message}

Web-researched recipe brief:
{compact_research}

Produce the required JSON now."""
        response_payload = await _post_groq(
            api_key=api_key,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    try:
        parsed = ParsedMeal.model_validate_json(_response_content(response_payload))
    except ValidationError as exc:
        raise MealPlanParseError("Groq returned an invalid recipe structure.") from exc

    _validate_ingredient_limits(parsed.ingredients)
    return parsed




def _compact_research(value: str, max_characters: int = 12000) -> str:
    """Keep the useful recipe brief while preventing an oversized second request.

    Groq Compound can occasionally return a very long web-research response.
    Only the concise recipe facts are needed by the structuring model, so the
    text is normalized and capped before being included in the next request.
    """

    normalized = "\n".join(
        line.strip()
        for line in value.splitlines()
        if line.strip()
    )

    if len(normalized) <= max_characters:
        return normalized

    head_size = int(max_characters * 0.8)
    tail_size = max_characters - head_size

    return (
        normalized[:head_size]
        + "\n\n[Research shortened by WasteWise to fit Groq request limits.]\n\n"
        + normalized[-tail_size:]
    )



async def _structure_recipe_directly(
    message: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> ParsedMeal:
    """Fallback parser used when Groq Compound web research is rejected.

    This keeps meal planning available by asking the structured model to infer
    a practical recipe directly from the user's request.
    """

    model = os.getenv(
        "GROQ_STRUCTURED_MODEL",
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    ).strip()

    system_prompt = """Convert a natural-language meal request into JSON for a grocery-list application.

Return only one JSON object with these exact keys:
- dish_name: concise dish name
- servings: integer 1-30; use 4 only when genuinely missing
- times: integer 1-14; how many times the dish will be cooked; use 1 only when missing
- ingredients: array for ONE cooking occurrence at the stated servings. Each item must have product_name, quantity, unit, category.
- assumptions: array of short strings explaining defaults or interpretations

Allowed units: g, kg, ml, l, piece, pack.
Allowed categories: beverage, dairy, fruit, grain, meat, snack, vegetable, other.
Use generic ingredient names, not brands. Exclude only water. Merge duplicate ingredients.
Convert spoon/cup measures into practical grams or millilitres.
Never return zero or negative quantities.

Return the COMPLETE ingredient list for the requested dish. Do not output only
a few representative ingredients. Preserve foods explicitly named in the
request whenever they function as ingredients or recipe bases. Do not silently
reinterpret the requested dish as a different preparation. Include the main
protein or base, vegetables, aromatics, cooking fat, spices, seasoning, and
garnish whenever they are normally used. Do not remove ingredients because they
might already be in the pantry; the grocery engine performs pantry subtraction
after this step. Infer a realistic household recipe from common culinary
knowledge."""

    user_prompt = f"""Meal request:
{message}

Produce the required JSON now."""

    payload = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    response_payload = await _post_groq(
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )

    try:
        parsed = ParsedMeal.model_validate_json(_response_content(response_payload))
    except ValidationError as exc:
        raise MealPlanParseError(
            "Groq returned an invalid recipe structure."
        ) from exc

    _validate_ingredient_limits(parsed.ingredients)
    return parsed





def _normalize_food_tokens(value: str) -> tuple[str, ...]:
    """Normalize an ingredient name without using a food or dish whitelist."""

    stop_words = {
        "a",
        "an",
        "and",
        "approximately",
        "about",
        "as",
        "at",
        "for",
        "fresh",
        "large",
        "medium",
        "of",
        "one",
        "per",
        "small",
        "the",
        "to",
        "taste",
        "used",
        "using",
    }

    normalized: list[str] = []

    for raw_token in re.findall(r"[a-zA-Z]+", value.casefold()):
        token = raw_token

        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("oes"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("es"):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s"):
            token = token[:-1]

        if len(token) >= 2 and token not in stop_words:
            normalized.append(token)

    return tuple(dict.fromkeys(normalized))


def _extract_json_object(value: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from research output."""

    candidate = value.strip()
    if candidate.startswith("```"):
        candidate = re.sub(
            r"^```(?:json)?\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(r"\s*```$", "", candidate)

    attempts = [candidate]
    first_brace = candidate.find("{")
    last_brace = candidate.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        attempts.append(candidate[first_brace : last_brace + 1])

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
        except (TypeError, ValueError):
            continue

        if isinstance(parsed, dict):
            return parsed

    return None


def _ingredient_names_from_json(value: Any) -> list[str]:
    """Collect ingredient names from a structured research response."""

    if not isinstance(value, dict):
        return []

    ingredients = value.get("ingredients")
    if not isinstance(ingredients, list):
        return []

    names: list[str] = []
    seen: set[str] = set()

    for item in ingredients:
        name = ""

        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            for key in (
                "product_name",
                "ingredient_name",
                "name",
                "ingredient",
            ):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    name = candidate
                    break

        cleaned = " ".join(name.strip().split())
        normalized = cleaned.casefold()

        if cleaned and normalized not in seen:
            names.append(cleaned)
            seen.add(normalized)

    return names


def _ingredient_names_from_text(research: str) -> list[str]:
    """Fallback extraction for concise non-JSON research responses."""

    if not research.strip():
        return []

    quantity = r"(?:\d+(?:\.\d+)?|\d+\s*/\s*\d+)"
    unit = (
        r"(?:kg|g|mg|ml|l|litres?|liters?|grams?|kilograms?|"
        r"cups?|tablespoons?|tbsp|teaspoons?|tsp|pieces?|packs?)"
    )
    boundary = r"(?=,|;|\band\b|\.|\n|$)"

    quantity_first = re.compile(
        rf"\b{quantity}\s*{unit}\s+"
        rf"(?P<name>[a-zA-Z][a-zA-Z '\-]{{1,100}}?){boundary}",
        re.IGNORECASE,
    )

    names: list[str] = []
    seen: set[str] = set()

    for match in quantity_first.finditer(research):
        name = " ".join(match.group("name").strip(" -:").split())
        name = re.sub(
            r"\b(?:per cooking|per serving|for garnish|to taste)\b.*$",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()

        normalized = name.casefold()
        if name and normalized not in seen:
            names.append(name)
            seen.add(normalized)

    # Handle clearly labelled forms such as "Onion: 500 g". Requiring a
    # newline or list marker prevents text like "for 6 people: 1.5 kg" from
    # being mistaken for an ingredient.
    labelled = re.compile(
        rf"(?:^|\n)\s*(?:[-*•]\s*)?"
        rf"(?P<name>[a-zA-Z][a-zA-Z '\-]{{1,100}}?)\s*:\s*"
        rf"{quantity}\s*{unit}\b",
        re.IGNORECASE,
    )

    for match in labelled.finditer(research):
        name = " ".join(match.group("name").strip(" -:").split())
        normalized = name.casefold()

        if name and normalized not in seen:
            names.append(name)
            seen.add(normalized)

    return names


def _research_ingredient_names(research: str) -> list[str]:
    """Read structured research first, then use a text compatibility fallback."""

    structured = _extract_json_object(research)
    names = _ingredient_names_from_json(structured)

    if names:
        return names

    return _ingredient_names_from_text(research)


def _ingredient_names_match(left: str, right: str) -> bool:
    """Compare generic ingredient names without loose one-token matching."""

    left_tokens = set(_normalize_food_tokens(left))
    right_tokens = set(_normalize_food_tokens(right))

    if not left_tokens or not right_tokens:
        return False

    if left_tokens == right_tokens:
        return True

    form_words = {
        "broth",
        "cream",
        "extract",
        "flour",
        "juice",
        "oil",
        "paste",
        "powder",
        "sauce",
        "stock",
        "syrup",
    }

    if (left_tokens & form_words) != (right_tokens & form_words):
        return False

    overlap = left_tokens & right_tokens
    coverage = len(overlap) / max(len(left_tokens), len(right_tokens))

    if coverage >= 0.75:
        return True

    left_text = " ".join(sorted(left_tokens))
    right_text = " ".join(sorted(right_tokens))

    return SequenceMatcher(None, left_text, right_text).ratio() >= 0.86


def _recipe_looks_incomplete(
    parsed: ParsedMeal,
    research: str,
) -> bool:
    """Detect meaningful ingredient loss from research to structured JSON."""

    researched_names = _research_ingredient_names(research)
    if not researched_names:
        return False

    parsed_names = [
        ingredient.product_name
        for ingredient in parsed.ingredients
    ]

    missing = [
        researched_name
        for researched_name in researched_names
        if not any(
            _ingredient_names_match(
                researched_name,
                parsed_name,
            )
            for parsed_name in parsed_names
        )
    ]

    if not missing:
        return False

    missing_ratio = len(missing) / len(researched_names)

    return len(missing) >= 2 or missing_ratio >= 0.25


async def _expand_incomplete_recipe(
    message: str,
    parsed: ParsedMeal,
    *,
    api_key: str,
    timeout_seconds: float,
) -> ParsedMeal:
    """Ask Groq once to repair an incomplete ingredient list."""

    model = os.getenv(
        "GROQ_STRUCTURED_MODEL",
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    ).strip()

    existing_json = parsed.model_dump_json()

    system_prompt = """You repair incomplete recipe JSON for a grocery-list application.

Return only one valid JSON object with these exact keys:
- dish_name
- servings
- times
- ingredients
- assumptions

Each ingredient must contain product_name, quantity, unit, and category.
Allowed units: g, kg, ml, l, piece, pack.
Allowed categories: beverage, dairy, fruit, grain, meat, snack, vegetable, other.

Produce the COMPLETE ingredient list for the requested dish for ONE cooking
occurrence at the stated servings. Retain valid existing ingredients and add
all commonly required missing ingredients: main protein or base, vegetables,
aromatics, cooking fat, spices, seasoning, and garnish. Exclude only water.
Use generic grocery names, merge duplicates, and never return zero or negative
quantities. Do not subtract pantry stock."""

    user_prompt = f"""Original meal request:
{message}

The previous JSON was incomplete or did not match the requested dish:
{existing_json}

Preserve foods explicitly named in the original request whenever they function
as ingredients or recipe bases. Retain every valid researched ingredient and do
not silently change the requested dish into a different preparation.

Return corrected and complete recipe JSON now."""

    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    response_payload = await _post_groq(
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )

    try:
        completed = ParsedMeal.model_validate_json(
            _response_content(response_payload)
        )
    except ValidationError as exc:
        raise MealPlanParseError(
            "Groq returned an invalid completed recipe structure."
        ) from exc

    _validate_ingredient_limits(completed.ingredients)

    # Never replace a better first answer with a shorter repair.
    if len(completed.ingredients) < len(parsed.ingredients):
        return parsed

    return completed


def _validate_ingredient_limits(ingredients: list[ParsedIngredient]) -> None:
    for ingredient in ingredients:
        quantity = ingredient.quantity
        if ingredient.unit in {"kg", "l"} and quantity > 100:
            raise MealPlanParseError("An AI ingredient quantity exceeded the safe limit.")
        if ingredient.unit in {"piece", "pack"} and quantity > 500:
            raise MealPlanParseError("An AI ingredient count exceeded the safe limit.")


def _merge_duplicate_ingredients(
    ingredients: list[ParsedIngredient],
    times: int,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for ingredient in ingredients:
        data = ingredient.model_dump()
        product_name = " ".join(data["product_name"].strip().split())
        key = (product_name.casefold(), data["unit"])
        multiplied_quantity = round(float(data["quantity"]) * times, 4)

        existing = merged.get(key)
        if existing is None:
            data["product_name"] = product_name
            data["quantity"] = multiplied_quantity
            merged[key] = data
        else:
            existing["quantity"] = round(
                float(existing["quantity"]) + multiplied_quantity,
                4,
            )

    return list(merged.values())


async def parse_meal_request(message: str) -> dict[str, Any]:
    """Research and parse any user-supplied recipe with Groq.

    There is intentionally no hardcoded dish list. The returned ingredient
    quantities are scaled for the requested cooking frequency before being
    passed to the grocery-list engine.
    """

    cleaned_message = " ".join(message.strip().split())
    if len(cleaned_message) < 3:
        raise MealPlanParseError("Please enter a meal or recipe to plan.")

    api_key = _require_api_key()
    timeout_seconds = _timeout_seconds()

    used_web_search = False
    sources: list[str] = []
    used_direct_fallback = False

    try:
        research, used_web_search, sources = await _research_recipe(
            cleaned_message,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

        parsed = await _structure_recipe(
            cleaned_message,
            research,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except GroqRequestTooLargeError:
        # The Compound web-search request can occasionally be rejected even
        # when the user's message is small. Fall back to the normal structured
        # model instead of failing the whole grocery flow.
        parsed = await _structure_recipe_directly(
            cleaned_message,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        used_direct_fallback = True

    require_web = os.getenv("GROQ_REQUIRE_WEB_SEARCH", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if require_web and not used_web_search and not used_direct_fallback:
        raise MealPlanParseError(
            "Groq did not execute web search for this recipe. Please try again."
        )

    if _recipe_looks_incomplete(
        parsed,
        research if not used_direct_fallback else "",
    ):
        parsed = await _expand_incomplete_recipe(
            cleaned_message,
            parsed,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    assumptions = list(parsed.assumptions)
    if used_direct_fallback:
        assumptions.append(
            "Recipe ingredients were inferred directly because Groq web research was unavailable."
        )
    elif not used_web_search:
        assumptions.append(
            "Groq Compound did not report a web-search tool call for this request."
        )
    elif sources:
        source_hosts: list[str] = []
        for url in sources:
            host = url.split("//", 1)[-1].split("/", 1)[0]
            if host and host not in source_hosts:
                source_hosts.append(host)
        if source_hosts:
            assumptions.append(
                "Recipe research sources: " + ", ".join(source_hosts[:5]) + "."
            )

    return {
        "dish_name": parsed.dish_name,
        "servings": parsed.servings,
        "times": parsed.times,
        "ingredients": _merge_duplicate_ingredients(
            parsed.ingredients,
            parsed.times,
        ),
        "assumptions": list(dict.fromkeys(assumptions)),
        "recipe_source": (
            "groq_web"
            if used_web_search
            else "groq_direct"
            if used_direct_fallback
            else "groq_compound"
        ),
    }