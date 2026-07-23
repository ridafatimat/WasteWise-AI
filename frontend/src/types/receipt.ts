export type ReceiptPackageUnit =
  | "g"
  | "kg"
  | "ml"
  | "l"
  | "oz"
  | "fl_oz"
  | "lb"
  | "gal"
  | "pint"
  | "quart"
  | "piece"
  | "pack"
  | "unknown";

export type ReceiptCategory =
  | "beverage"
  | "dairy"
  | "fruit"
  | "grain"
  | "meat"
  | "snack"
  | "vegetable"
  | "other";

export type ReceiptStorageLocation =
  | "fridge"
  | "freezer"
  | "pantry"
  | "unknown";

export type ReceiptPurchaseDateSource =
  | "receipt"
  | "upload_date";

export type ReceiptExpirySource =
  | "local_rule"
  | "gemini_estimate"
  | "category_default";

export type ReceiptJobStatus =
  | "queued"
  | "processing"
  | "completed"
  | "failed";

export interface ReceiptItem {
  raw_name: string;
  product_name: string;
  pantry_name: string | null;
  purchased_quantity: number | null;
  package_size: number | null;
  package_unit: ReceiptPackageUnit;
  unit_price: number | null;
  line_total: number | null;
  category: ReceiptCategory;
  location: ReceiptStorageLocation;
  is_food_item: boolean;
  uncertain_fields: string[];
  estimated_shelf_life_days: number | null;
  expiry_confidence: number | null;
  expiry_reason: string | null;
}

export interface ReceiptData {
  merchant_name: string | null;
  invoice_number: string | null;
  purchase_date: string | null;
  purchase_date_source: ReceiptPurchaseDateSource | null;
  currency: string;
  items_subtotal: number | null;
  tax_amount: number | null;
  tax_rate: number | null;
  service_charge: number | null;
  delivery_charge: number | null;
  other_charges: number | null;
  discount_amount: number | null;
  total_amount: number | null;
  payment_amount: number | null;
  change_amount: number | null;
  items: ReceiptItem[];
}

export interface ReceiptFinancialValidation {
  status: "reconciled" | "mismatch" | "unavailable";
  line_items_total: number;
  items_subtotal: number | null;
  calculated_total: number | null;
  receipt_total: number | null;
  difference: number | null;
  tolerance: number;
  missing_line_totals: number;
  notes: string[];
}

export interface ReceiptProcessSummary {
  items_extracted: number;
  items_created: number;
  items_updated: number;
  items_skipped: number;
}

export interface PantryReceiptChange {
  product_name: string;
  action: "created" | "updated" | "skipped";
  quantity_added: number | null;
  unit: string | null;
  pantry_item_id: string | null;
  expiry_date: string | null;
  expiry_source: ReceiptExpirySource | null;
  expiry_confidence: number | null;
  expiry_reason: string | null;
  reason: string | null;
}

export interface ReceiptScanResponse {
  success: boolean;
  receipt: ReceiptData;
  financial_validation: ReceiptFinancialValidation;
}

export interface ReceiptProcessResponse
  extends ReceiptScanResponse {
  summary: ReceiptProcessSummary;
  pantry_changes: PantryReceiptChange[];
}

export interface ReceiptJobResponse {
  job_id: string;
  status: ReceiptJobStatus;
  progress: number;
  stage: string;
  estimated_seconds_remaining: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: ReceiptProcessResponse | null;
  error: string | null;
}