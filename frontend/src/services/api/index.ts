import { api } from "./client";

import type {
  AuthUser,
  InventoryEvent,
  PantryItem,
  PantryItemCreate,
  PantryItemUpdate,
  RiskPrediction,
} from "@/types";

import type {
  ReceiptJobResponse,
  ReceiptProcessResponse,
  ReceiptScanResponse,
} from "@/types/receipt";

import type {
  RecipeSuggestionRequest,
  RecipeSuggestionResponse,
} from "@/types/recipe";


export type InventoryEventCreatePayload =
  {
    event_type:
      | "consumed"
      | "wasted"
      | "purchased"
      | "adjusted";

    quantity: number;
    notes?: string;
  };


// ---------------- Auth ----------------

export type RegisterPayload =
  | {
      name: string;
      email: string;
      password: string;
      household_name: string;
      household_invite_token?: never;
    }
  | {
      name: string;
      email: string;
      password: string;
      household_name?: never;
      household_invite_token: string;
    };

export type HouseholdInviteResponse = {
  household_id: string;
  household_name: string;
  invite_token: string;
  expires_in_hours: number;
};


export async function login(
  email: string,
  password: string,
) {
  const response =
    await api.post(
      "/auth/login",
      {
        email,
        password,
      },
    );

  return response.data as {
    access_token?: string;
    token?: string;
    token_type?: string;
    user?: AuthUser;
  };
}


export async function register(
  payload: RegisterPayload,
) {
  const response =
    await api.post(
      "/auth/register",
      payload,
    );

  return response.data;
}


export async function getMe() {
  const response =
    await api.get(
      "/auth/me",
    );

  return response.data as AuthUser;
}


export async function createHouseholdInvite():
  Promise<HouseholdInviteResponse> {
  const response =
    await api.post<
      HouseholdInviteResponse
    >(
      "/households/invite",
    );

  return response.data;
}


// ---------------- Pantry ----------------

export async function listPantryItems():
  Promise<PantryItem[]> {
  const response =
    await api.get(
      "/pantry-items",
    );

  const data =
    response.data;

  if (
    Array.isArray(data)
  ) {
    return data;
  }

  if (
    Array.isArray(
      data?.items,
    )
  ) {
    return data.items;
  }

  if (
    Array.isArray(
      data?.results,
    )
  ) {
    return data.results;
  }

  return [];
}


export async function getPantryItem(
  id: string,
): Promise<PantryItem> {
  const response =
    await api.get(
      `/pantry-items/${id}`,
    );

  return response.data as PantryItem;
}


export async function createPantryItem(
  payload: PantryItemCreate,
): Promise<PantryItem> {
  const response =
    await api.post(
      "/pantry-items",
      payload,
    );

  return response.data as PantryItem;
}


export async function updatePantryItem(
  id: string,
  payload: PantryItemUpdate,
): Promise<PantryItem> {
  const response =
    await api.patch(
      `/pantry-items/${id}`,
      payload,
    );

  return response.data as PantryItem;
}


export async function deletePantryItem(
  id: string,
): Promise<void> {
  await api.delete(
    `/pantry-items/${id}`,
  );
}


// ---------------- Events ----------------

export async function createInventoryEvent(
  pantryItemId: string,
  payload:
    InventoryEventCreatePayload,
): Promise<InventoryEvent> {
  const response =
    await api.post(
      `/pantry-items/${pantryItemId}/events`,
      payload,
    );

  return response.data as InventoryEvent;
}


export async function listInventoryEvents(
  pantryItemId?: string,
): Promise<InventoryEvent[]> {
  const url =
    pantryItemId
      ? `/pantry-items/${pantryItemId}/events`
      : "/inventory-events";

  try {
    const response =
      await api.get(url);

    const data =
      response.data;

    if (
      Array.isArray(data)
    ) {
      return data;
    }

    if (
      Array.isArray(
        data?.items,
      )
    ) {
      return data.items;
    }

    return [];
  } catch {
    return [];
  }
}


// ---------------- Predictions ----------------

export async function getWasteRisk():
  Promise<RiskPrediction[]> {
  const response =
    await api.get(
      "/predictions/waste-risk",
    );

  const data =
    response.data;

  if (
    Array.isArray(data)
  ) {
    return data;
  }

  if (
    Array.isArray(
      data?.items,
    )
  ) {
    return data.items;
  }

  return [];
}


// ---------------- Receipts ----------------

const RECEIPT_REQUEST_TIMEOUT_MS =
  120000;


function buildReceiptFormData(
  file: File,
) {
  const formData =
    new FormData();

  formData.append(
    "file",
    file,
    file.name,
  );

  return formData;
}


export async function scanReceipt(
  file: File,
  onProgress?: (
    progress: number,
  ) => void,
): Promise<ReceiptScanResponse> {
  const response =
    await api.post<
      ReceiptScanResponse
    >(
      "/receipts/scan",
      buildReceiptFormData(
        file,
      ),
      {
        headers: {
          "Content-Type":
            "multipart/form-data",
        },

        timeout:
          RECEIPT_REQUEST_TIMEOUT_MS,

        onUploadProgress:
          (event) => {
            if (
              onProgress &&
              event.total
            ) {
              onProgress(
                Math.round(
                  (
                    event.loaded /
                    event.total
                  ) *
                    100,
                ),
              );
            }
          },
      },
    );

  return response.data;
}


/*
 * Kept for backward compatibility.
 * Existing pages can still use the original synchronous endpoint.
 */
export async function uploadReceipt(
  file: File,
  onProgress?: (
    progress: number,
  ) => void,
): Promise<ReceiptProcessResponse> {
  const response =
    await api.post<
      ReceiptProcessResponse
    >(
      "/receipts/process",
      buildReceiptFormData(
        file,
      ),
      {
        headers: {
          "Content-Type":
            "multipart/form-data",
        },

        timeout:
          RECEIPT_REQUEST_TIMEOUT_MS,

        onUploadProgress:
          (event) => {
            if (
              onProgress &&
              event.total
            ) {
              onProgress(
                Math.round(
                  (
                    event.loaded /
                    event.total
                  ) *
                    100,
                ),
              );
            }
          },
      },
    );

  return response.data;
}


/*
 * New background receipt-processing flow.
 */
export async function startReceiptJob(
  file: File,
  onProgress?: (
    progress: number,
  ) => void,
): Promise<ReceiptJobResponse> {
  const response =
    await api.post<
      ReceiptJobResponse
    >(
      "/receipts/jobs",
      buildReceiptFormData(
        file,
      ),
      {
        headers: {
          "Content-Type":
            "multipart/form-data",
        },

        timeout:
          RECEIPT_REQUEST_TIMEOUT_MS,

        onUploadProgress:
          (event) => {
            if (
              onProgress &&
              event.total
            ) {
              onProgress(
                Math.round(
                  (
                    event.loaded /
                    event.total
                  ) *
                    100,
                ),
              );
            }
          },
      },
    );

  return response.data;
}


export async function getReceiptJob(
  jobId: string,
): Promise<ReceiptJobResponse> {
  const response =
    await api.get<
      ReceiptJobResponse
    >(
      `/receipts/jobs/${jobId}`,
      {
        timeout: 30000,
      },
    );

  return response.data;
}


function wait(
  milliseconds: number,
) {
  return new Promise<void>(
    (resolve) => {
      window.setTimeout(
        resolve,
        milliseconds,
      );
    },
  );
}


export async function waitForReceiptJob(
  jobId: string,
  onUpdate?: (
    job: ReceiptJobResponse,
  ) => void,
  signal?: AbortSignal,
): Promise<ReceiptProcessResponse> {
  const startedAt =
    Date.now();

  const maximumWaitMs =
    15 * 60 * 1000;

  while (true) {
    if (signal?.aborted) {
      throw new Error(
        "Receipt processing was cancelled.",
      );
    }

    const job =
      await getReceiptJob(
        jobId,
      );

    onUpdate?.(job);

    if (
      job.status ===
      "completed"
    ) {
      if (!job.result) {
        throw new Error(
          "Receipt processing completed without a result.",
        );
      }

      return job.result;
    }

    if (
      job.status ===
      "failed"
    ) {
      throw new Error(
        job.error ||
        "Receipt processing failed.",
      );
    }

    if (
      Date.now() -
        startedAt >
      maximumWaitMs
    ) {
      throw new Error(
        "Receipt processing is still taking longer than expected. Please check again shortly.",
      );
    }

    await wait(1500);
  }
}


// ---------------- Recommendations ----------------

export async function getGroceryRecommendations() {
  const response =
    await api.get(
      "/recommendations/grocery",
    );

  return response.data;
}


export async function getRecipeRecommendations(
  payload:
    RecipeSuggestionRequest,
): Promise<RecipeSuggestionResponse> {
  const response =
    await api.post<
      RecipeSuggestionResponse
    >(
      "/recommendations/recipes",
      payload,
      {
        timeout: 180000,
      },
    );

  return response.data;
}