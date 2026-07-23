import asyncio
import json

from app import groq_service


def test_any_recipe_is_researched_and_scaled(
    monkeypatch,
):
    monkeypatch.setenv(
        "GROQ_API_KEY",
        "test-key",
    )
    monkeypatch.setenv(
        "GROQ_RECIPE_RESEARCH_MODEL",
        "groq/compound-mini",
    )
    monkeypatch.setenv(
        "GROQ_STRUCTURED_MODEL",
        "llama-3.3-70b-versatile",
    )

    calls = []

    async def fake_post_groq(**kwargs):
        calls.append(
            kwargs["payload"]
        )

        if len(calls) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Mutton Nihari for 6 people: "
                                "1.5 kg mutton, 500 g onions "
                                "and 60 g flour per cooking. "
                                "Cook twice."
                            ),
                            "executed_tools": [
                                {
                                    "type": "web_search",
                                    "search_results": [
                                        {
                                            "url": (
                                                "https://example.com/"
                                                "nihari-recipe"
                                            )
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ]
            }

        structured = {
            "dish_name": "Mutton Nihari",
            "servings": 6,
            "times": 2,
            "ingredients": [
                {
                    "product_name": "Mutton",
                    "quantity": 1.5,
                    "unit": "kg",
                    "category": "meat",
                },
                {
                    "product_name": "Onion",
                    "quantity": 500,
                    "unit": "g",
                    "category": "vegetable",
                },
                {
                    "product_name": "Flour",
                    "quantity": 60,
                    "unit": "g",
                    "category": "grain",
                },
            ],
            "assumptions": [],
        }

        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            structured
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        groq_service,
        "_post_groq",
        fake_post_groq,
    )

    result = asyncio.run(
        groq_service.parse_meal_request(
            (
                "I will make mutton nihari twice "
                "this week for 6 people"
            )
        )
    )

    assert len(calls) == 2

    assert (
        calls[0]["model"]
        == "groq/compound-mini"
    )

    assert (
        calls[0]["compound_custom"][
            "tools"
        ]["enabled_tools"]
        == [
            "web_search"
        ]
    )

    assert (
        result["dish_name"]
        == "Mutton Nihari"
    )

    assert (
        result["recipe_source"]
        == "groq_web"
    )

    assert (
        result["ingredients"][0][
            "quantity"
        ]
        == 3.0
    )

    assert (
        result["ingredients"][1][
            "quantity"
        ]
        == 1000.0
    )

    assert (
        result["ingredients"][2][
            "quantity"
        ]
        == 120.0
    )

    assert any(
        "example.com" in item
        for item in result[
            "assumptions"
        ]
    )