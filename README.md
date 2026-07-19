# WasteWise AI

WasteWise AI is a smart household pantry and food-waste management system. It helps users track pantry items, scan grocery receipts, identify products close to expiry, generate grocery lists, receive recipe suggestions, and estimate the risk of food being wasted.

The application combines a React frontend, a FastAPI backend, PostgreSQL, OCR and LLM-based receipt processing, and machine-learning waste-risk prediction.

---

## Main Features

### Smart Pantry

- Add, update, view, and remove pantry items.
- Track quantity, unit, category, storage location, purchase date, and expiry date.
- Keep separate pantry batches for purchases made on different dates.
- Record consumed, wasted, expired, adjusted, and updated inventory events.
- Share pantry data between members of the same household.

### Receipt Scanner

- Upload JPG, PNG, or WEBP receipt images.
- Extract merchant, date, time, products, quantities, prices, tax, and total.
- Convert branded receipt names into pantry-friendly product names.
- Validate the receipt subtotal against the final total.
- Create separate pantry batches from edible products.
- Skip non-edible products such as electronics, stationery, utensils, and household goods.
- Show a clear “No edible items found” message when a receipt contains no pantry items.

### Rescue Mode

- Shows active pantry items that are close to expiry.
- Excludes products that have already expired.
- Prioritizes the earliest-expiring products.
- Helps users consume food before it becomes waste.

### Waste-Risk Prediction

- Uses a trained logistic-regression model to estimate the probability that a pantry item may be wasted.
- Uses product category, storage location, quantity, purchase date, and days remaining until expiry.
- Supports household-specific retraining after enough new consumption or waste outcomes are collected.

### Grocery Recommendations

- Generates grocery lists using household pantry quantities and consumption patterns.
- Accepts natural-language meal plans, such as `Chicken karahi for 4 people this week`.
- Uses Groq to interpret dishes, servings, frequency, and ingredients.
- Subtracts ingredients already available in the pantry.
- Supports shopping mode.
- Adds purchased products to the pantry with meaningful category, unit, and location values.
- Supports grocery-list history and PDF download.

### Recipe Suggestions

- Suggests recipes using products expiring today or within the next few days.
- Uses Groq to generate practical meal ideas.
- Helps reduce avoidable household food waste.

### Dashboard and History

- Displays pantry summaries and items requiring attention.
- Shows consumed, wasted, and expired inventory activity.
- Provides household-level history and waste insights.

---

## Technology Stack

### Frontend

- React
- TypeScript
- Vite
- TanStack Router
- TanStack Query
- Tailwind CSS
- shadcn/ui
- Framer Motion
- Lucide React
- Sonner

### Backend

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- PostgreSQL
- JWT authentication
- Uvicorn

### AI and Machine Learning

- Groq API for grocery and recipe reasoning
- OCR and structured receipt extraction
- scikit-learn
- Logistic Regression
- pandas
- NumPy
- joblib

---

## System Flow

```text
User
  |
  v
React + TypeScript Frontend
  |
  v
FastAPI REST API
  |
  +----------------------+
  |                      |
  v                      v
PostgreSQL           AI / ML Services
  |                      |
  |                      +-- Receipt extraction
  |                      +-- Groq recommendations
  |                      +-- Waste-risk prediction
  |
  v
Households, pantry items, events,
grocery lists, receipts, and history
```

---

## Project Structure

```text
WasteWise-AI/
|
|-- backend/
|   |-- app/
|   |   |-- auth.py
|   |   |-- database.py
|   |   |-- grocery_service.py
|   |   |-- main.py
|   |   |-- ml.py
|   |   |-- models.py
|   |   |-- receipt_pantry_service.py
|   |   |-- schemas.py
|   |   `-- services.py
|   |
|   |-- artifacts/
|   |   `-- waste_risk_model.joblib
|   |
|   |-- training/
|   |   `-- train.py
|   |
|   `-- requirements.txt
|
|-- frontend/
|   |-- public/
|   |-- src/
|   |   |-- components/
|   |   |-- routes/
|   |   |-- services/
|   |   |-- types/
|   |   `-- main.tsx
|   |
|   |-- package.json
|   `-- vite.config.ts
|
`-- README.md
```

---

## Prerequisites

Install the following before running the project:

- Python 3.10 or newer
- Node.js 18 or newer
- npm
- PostgreSQL
- Git

---

## Backend Setup

Open a terminal in the project root:

```powershell
cd backend
```

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
pip install -r requirements.txt
```

Create a backend `.env` file and add the required configuration.

Example:

```env
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/wastewise
SECRET_KEY=replace_with_a_secure_secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
```

Use the environment-variable names already defined in the backend code if they differ from the example above.

Start the backend:

```powershell
uvicorn app.main:app --reload
```

The backend normally runs at:

```text
http://127.0.0.1:8000
```

Health check:

```text
GET /health
```

---

## Frontend Setup

Open another terminal:

```powershell
cd frontend
```

Install dependencies:

```powershell
npm install
```

Create a frontend `.env` file:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

Start the frontend:

```powershell
npm run dev
```

The frontend normally runs at:

```text
http://localhost:5173
```

---

## Main API Routes

The backend uses the `/api/v1` base path.

### Authentication

```text
POST /auth/register
POST /auth/login
GET  /auth/me
```

### Pantry

```text
GET    /pantry-items
POST   /pantry-items
PATCH  /pantry-items/{item_id}
DELETE /pantry-items/{item_id}
POST   /pantry-items/{item_id}/events
GET    /inventory-events
```

### Dashboard

```text
GET /dashboard/rescue-mode
```

### Grocery Recommendations

```text
POST /recommendations/grocery
```

### Recipe Recommendations

```text
POST /recommendations/recipes
```

### Receipt Processing

```text
POST /receipts/scan
POST /receipts/process
```

The frontend may call a combined receipt-upload service depending on the current implementation.

---

## Receipt Processing Logic

```text
Receipt image
    |
    v
File validation
    |
    v
OCR / structured extraction
    |
    v
Merchant, date, items, prices and total
    |
    v
Financial reconciliation
    |
    v
Product classification
    |
    +-- Edible item ------> Create pantry batch
    |
    `-- Non-edible item --> Skip item
```

When every extracted product is non-edible:

- The receipt is still processed successfully.
- No pantry batch is created.
- The user sees a “No edible items found” message.
- The Smart Pantry button is not shown for that result.

---

## Waste-Risk Model

The global baseline model is trained from historical food-expiry data.

### Main Features

```text
purchase_month
purchase_day_of_week
days_until_expiry
quantity
item_category
storage_location
```

### Training

Run the training script from the backend directory:

```powershell
python training/train.py
```

The trained model is saved as:

```text
backend/artifacts/waste_risk_model.joblib
```

### Household Retraining

A household-specific model can be retrained after:

- At least five new known outcomes are available.
- At least two days have passed since the previous household training.

Outcomes include consumed, wasted, and expired pantry events.

---

## Git Workflow

Check changed files:

```powershell
git status
```

Stage all project changes:

```powershell
git add .
```

Commit:

```powershell
git commit -m "Describe the completed change"
```

Push to GitHub:

```powershell
git push origin master
```

For a single file:

```powershell
git add frontend/src/routes/receipts.tsx
git commit -m "Handle receipts with no edible items"
git push origin master
```

---

## Testing Receipt Types

Test the scanner with:

1. A normal grocery receipt containing edible products.
2. A mixed receipt containing edible and non-edible products.
3. A receipt containing only non-edible products.
4. A low-quality or partially visible receipt.
5. A receipt with tax, discount, or extra charges.
6. Two receipts containing the same products but different purchase times.

Expected behavior for a non-edible receipt:

```text
items_created = 0
pantry_changes = []
No edible items found
```

---


