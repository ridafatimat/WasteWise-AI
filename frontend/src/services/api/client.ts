import axios, {
  AxiosError,
} from "axios";

const BASE_URL =
  (
    import.meta.env
      .VITE_API_BASE_URL as string
  ) ||
  "http://127.0.0.1:8000/api/v1";

export const TOKEN_KEY =
  "wastewise_token";

type ValidationDetail = {
  loc?: unknown[];
  msg?: string;
};

type ApiErrorBody = {
  detail?:
    | string
    | ValidationDetail[];
  message?: string;
};

export const api = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type":
      "application/json",
  },
  timeout: 20000,
});

api.interceptors.request.use(
  (config) => {
    if (
      typeof window !==
      "undefined"
    ) {
      const token =
        localStorage.getItem(
          TOKEN_KEY,
        );

      if (token) {
        config.headers =
          config.headers ?? {};

        (
          config.headers as Record<
            string,
            string
          >
        ).Authorization =
          `Bearer ${token}`;
      }
    }

    return config;
  },
);

api.interceptors.response.use(
  (response) => response,

  (error: AxiosError) => {
    if (
      error.response?.status ===
        401 &&
      typeof window !==
        "undefined"
    ) {
      localStorage.removeItem(
        TOKEN_KEY,
      );
    }

    return Promise.reject(error);
  },
);

function extractBackendMessage(
  data:
    | ApiErrorBody
    | string
    | undefined,
): string | null {
  if (
    typeof data === "string" &&
    data.trim()
  ) {
    return data;
  }

  if (
    !data ||
    typeof data !== "object"
  ) {
    return null;
  }

  if (
    typeof data.detail ===
      "string" &&
    data.detail.trim()
  ) {
    return data.detail;
  }

  if (
    Array.isArray(data.detail)
  ) {
    const messages =
      data.detail
        .map((detail) => {
          const field =
            Array.isArray(
              detail.loc,
            )
              ? detail.loc[
                  detail.loc
                    .length - 1
                ]
              : "field";

          const message =
            typeof detail.msg ===
            "string"
              ? detail.msg
              : "Invalid value";

          return `${String(
            field,
          )}: ${message}`;
        })
        .filter(Boolean);

    if (
      messages.length > 0
    ) {
      return messages.join(
        "; ",
      );
    }
  }

  if (
    typeof data.message ===
      "string" &&
    data.message.trim()
  ) {
    return data.message;
  }

  return null;
}

export function extractApiError(
  err: unknown,
): string {
  /*
   * Preserve all existing Axios/backend error messages first.
   *
   * The new background receipt job can also throw a normal JavaScript
   * Error when the job reports a failed status. That non-Axios error is
   * handled only after Axios errors, so messages such as the 409 duplicate
   * receipt message continue to work exactly as before.
   */
  if (
    axios.isAxiosError(err)
  ) {
    const error =
      err as AxiosError<
        ApiErrorBody | string
      >;

    if (
      error.code ===
        "ECONNABORTED" ||
      error.code ===
        "ETIMEDOUT"
    ) {
      return (
        "Receipt processing took too long. " +
        "Please try again with a clearer or smaller image."
      );
    }

    if (!error.response) {
      if (
        typeof navigator !==
          "undefined" &&
        !navigator.onLine
      ) {
        return (
          "You appear to be offline. " +
          "Check your internet connection and try again."
        );
      }

      return (
        "WasteWise could not reach the server. " +
        "Please check your connection and try again."
      );
    }

    const backendMessage =
      extractBackendMessage(
        error.response.data,
      );

    if (backendMessage) {
      return backendMessage;
    }

    switch (
      error.response.status
    ) {
      case 400:
        return (
          "The uploaded receipt could not be processed."
        );

      case 401:
        return (
          "Your session has expired. Please log in again."
        );

      case 409:
        return (
          "This receipt has already been processed."
        );

      case 413:
        return (
          "Receipt image must be 10 MB or smaller."
        );

      case 415:
        return (
          "Unsupported receipt format. " +
          "Upload a JPG, JPEG, PNG, or WEBP image."
        );

      case 422:
        return (
          "The image does not contain a readable receipt. " +
          "Please upload a clearer receipt image."
        );

      case 429:
        return (
          "The receipt service is receiving too many requests. " +
          "Please wait a moment and try again."
        );

      case 500:
        return (
          "The receipt was scanned, but the pantry could not be updated. " +
          "No pantry changes were saved."
        );

      case 502:
        return (
          "The receipt AI returned an invalid response. " +
          "Please try again."
        );

      case 503:
        return (
          "The receipt AI service is temporarily unavailable. " +
          "Please try again shortly."
        );

      case 504:
        return (
          "Receipt processing took too long. " +
          "Please try again with a clearer or smaller image."
        );

      default:
        return (
          `Request failed (${error.response.status}). ` +
          "Please try again."
        );
    }
  }

  /*
   * New logic needed for background jobs:
   * waitForReceiptJob() throws a normal Error when the saved job reaches
   * "failed", is cancelled, or completes without a result.
   */
  if (
    err instanceof Error &&
    err.message.trim()
  ) {
    return err.message;
  }

  return (
    "Something unexpected happened. " +
    "Please try again."
  );
}

export function parseFieldErrors(
  err: unknown,
): Record<string, string> {
  const output: Record<
    string,
    string
  > = {};

  if (
    !axios.isAxiosError(err)
  ) {
    return output;
  }

  const detail = (
    err as AxiosError<ApiErrorBody>
  ).response?.data?.detail;

  if (
    !Array.isArray(detail)
  ) {
    return output;
  }

  for (
    const item of detail
  ) {
    if (
      !Array.isArray(item.loc)
    ) {
      continue;
    }

    const key =
      item.loc[
        item.loc.length - 1
      ];

    if (
      typeof key ===
        "string" &&
      typeof item.msg ===
        "string"
    ) {
      output[key] =
        item.msg;
    }
  }

  return output;
}