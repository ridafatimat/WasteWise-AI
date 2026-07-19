import {
  createFileRoute,
  Link,
} from "@tanstack/react-router";
import {
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  FileImage,
  Loader2,
  Package,
  PackageCheck,
  ReceiptText,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Store,
  UploadCloud,
  WalletCards,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { uploadReceipt } from "@/services/api";
import { extractApiError } from "@/services/api/client";
import type {
  PantryReceiptChange,
  ReceiptItem,
  ReceiptProcessResponse,
} from "@/types/receipt";

export const Route = createFileRoute("/receipts")({
  head: () => ({
    meta: [
      {
        title: "Receipt Upload — WasteWise AI",
      },
    ],
  }),
  component: ReceiptsPage,
});

const MAX_FILE_SIZE = 10 * 1024 * 1024;

const ALLOWED_FILE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

function formatMoney(
  value: number | null,
  currency: string,
) {
  if (value === null) {
    return "—";
  }

  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function formatDate(value: string | null) {
  if (!value) {
    return "Not available";
  }

  const parsed = new Date(`${value}T00:00:00`);

  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(parsed);
}

function formatPackage(item: ReceiptItem) {
  if (
    item.package_size === null ||
    item.package_unit === "unknown"
  ) {
    return "No package size";
  }

  const labels: Record<string, string> = {
    fl_oz: "fl oz",
    l: "L",
  };

  const unit =
    labels[item.package_unit] ??
    item.package_unit;

  return `${item.package_size} ${unit}`;
}

function formatPurchasedQuantity(item: ReceiptItem) {
  const quantity = item.purchased_quantity ?? 1;

  if (
    item.package_size === null &&
    [
      "g",
      "kg",
      "ml",
      "l",
      "oz",
      "fl_oz",
      "lb",
      "gal",
      "pint",
      "quart",
    ].includes(item.package_unit)
  ) {
    const unit =
      item.package_unit === "fl_oz"
        ? "fl oz"
        : item.package_unit;

    return `${quantity} ${unit}`;
  }

  return `${quantity}`;
}

function formatChangeQuantity(
  change: PantryReceiptChange,
) {
  if (change.quantity_added === null) {
    return "—";
  }

  return `${change.quantity_added} ${change.unit ?? ""}`.trim();
}

function ReceiptsPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [result, setResult] =
    useState<ReceiptProcessResponse | null>(null);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const mutation = useMutation({
    mutationFn: async (selectedFile: File) =>
      uploadReceipt(
        selectedFile,
        setUploadProgress,
      ),
    onSuccess: async (data) => {
      setResult(data);

      const hasEdibleItems =
        data.summary.items_created > 0 ||
        data.pantry_changes.some(
          (change) => change.action === "created",
        );

      if (!hasEdibleItems) {
        toast.info(
          "Receipt scanned, but no edible pantry items were found.",
        );
        return;
      }

      toast.success(
        `${data.summary.items_created} new pantry batch${
          data.summary.items_created === 1 ? "" : "es"
        } added.`,
      );

      await queryClient.invalidateQueries({
        queryKey: ["pantry"],
      });
    },
    onError: (error) => {
      toast.error(extractApiError(error));
    },
  });

  const isProcessing = mutation.isPending;
  const hasEdibleItems =
    result !== null &&
    (result.summary.items_created > 0 ||
      result.pantry_changes.some(
        (change) => change.action === "created",
      ));

  const clearSelection = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }

    setFile(null);
    setPreviewUrl(null);
    setResult(null);
    setUploadProgress(0);
    mutation.reset();

    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  const selectFile = (selectedFile: File) => {
    if (!ALLOWED_FILE_TYPES.has(selectedFile.type)) {
      toast.error(
        "Upload a JPG, JPEG, PNG, or WEBP receipt image.",
      );
      return;
    }

    if (selectedFile.size > MAX_FILE_SIZE) {
      toast.error(
        "Receipt image must be 10 MB or smaller.",
      );
      return;
    }

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }

    setFile(selectedFile);
    setPreviewUrl(
      URL.createObjectURL(selectedFile),
    );
    setResult(null);
    setUploadProgress(0);
    mutation.reset();
  };

  const handleInputChange = (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const selectedFile = event.target.files?.[0];

    if (selectedFile) {
      selectFile(selectedFile);
    }
  };

  const handleDrop = (
    event: DragEvent<HTMLDivElement>,
  ) => {
    event.preventDefault();
    setDragActive(false);

    if (isProcessing) {
      return;
    }

    const selectedFile =
      event.dataTransfer.files?.[0];

    if (selectedFile) {
      selectFile(selectedFile);
    }
  };

  const handleProcess = () => {
    if (!file) {
      toast.error("Choose a receipt image first.");
      return;
    }

    setResult(null);
    setUploadProgress(0);
    mutation.mutate(file);
  };

  return (
    <RequireAuth>
      <AppShell title="Receipt Upload">
        <div className="mx-auto max-w-7xl space-y-7">
          <motion.section
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="relative overflow-hidden rounded-[28px] border border-primary/20 bg-card p-5 sm:p-7"
          >
            <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-primary/15 blur-3xl" />
            <div className="pointer-events-none absolute -bottom-32 left-1/3 h-64 w-64 rounded-full bg-fuchsia-500/10 blur-3xl" />

            <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary">
                  <Sparkles className="h-3.5 w-3.5" />
                  AI receipt scanner
                </div>

                <h2 className="mt-4 max-w-2xl text-2xl font-bold tracking-tight sm:text-4xl">
                  Scan once. Stock your pantry automatically.
                </h2>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
                  Upload a clear receipt image. WasteWise reads the products,
                  quantities, prices and dates, then creates separate pantry
                  batches for you.
                </p>
              </div>

              <div className="grid grid-cols-3 gap-2 sm:min-w-[430px]">
                <ProcessStep
                  number="01"
                  icon={UploadCloud}
                  label="Upload"
                />
                <ProcessStep
                  number="02"
                  icon={ScanLine}
                  label="AI reads"
                />
                <ProcessStep
                  number="03"
                  icon={PackageCheck}
                  label="Pantry updates"
                />
              </div>
            </div>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="overflow-hidden rounded-[30px] border border-border/70 bg-card shadow-sm"
          >
            <div className="grid xl:grid-cols-[1.05fr_0.95fr]">
              <div className="relative p-5 sm:p-7 lg:p-8">
                <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
                      Upload receipt
                    </p>
                    <h3 className="mt-2 text-xl font-semibold sm:text-2xl">
                      Add a new grocery purchase
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      Use a sharp, well-lit image for the most accurate result.
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2 text-[11px] font-medium text-muted-foreground">
                    <span className="rounded-full border border-border bg-background/50 px-2.5 py-1">
                      JPG · PNG · WEBP
                    </span>
                    <span className="rounded-full border border-border bg-background/50 px-2.5 py-1">
                      Max 10 MB
                    </span>
                  </div>
                </div>

                <input
                  ref={inputRef}
                  id="receipt-file"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.jfif,.png,.webp"
                  onChange={handleInputChange}
                  className="hidden"
                  disabled={isProcessing}
                />

                <div
                  onDragEnter={(event) => {
                    event.preventDefault();
                    if (!isProcessing) {
                      setDragActive(true);
                    }
                  }}
                  onDragOver={(event) => {
                    event.preventDefault();
                  }}
                  onDragLeave={(event) => {
                    event.preventDefault();
                    setDragActive(false);
                  }}
                  onDrop={handleDrop}
                  onClick={() => {
                    if (!isProcessing) {
                      inputRef.current?.click();
                    }
                  }}
                  className={cn(
                    "group relative cursor-pointer overflow-hidden rounded-[26px] border border-dashed p-6 text-center transition duration-300 sm:p-10",
                    dragActive
                      ? "border-primary bg-primary/10 shadow-glow"
                      : file
                        ? "border-primary/35 bg-primary/[0.04]"
                        : "border-border bg-background/35 hover:border-primary/45 hover:bg-primary/[0.04]",
                    isProcessing &&
                      "pointer-events-none cursor-default opacity-70",
                  )}
                >
                  <div className="pointer-events-none absolute inset-x-16 top-0 h-24 rounded-full bg-primary/10 blur-3xl opacity-0 transition group-hover:opacity-100" />

                  <div className="relative">
                    <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-[0_0_40px_rgba(236,72,153,0.12)] transition duration-300 group-hover:-translate-y-1 group-hover:scale-105">
                      {file ? (
                        <FileImage className="h-7 w-7" />
                      ) : (
                        <UploadCloud className="h-7 w-7" />
                      )}
                    </div>

                    <p className="mt-5 text-base font-semibold sm:text-lg">
                      {file
                        ? "Receipt ready to scan"
                        : "Drop your receipt here"}
                    </p>

                    <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
                      {file
                        ? "You can replace it by dropping another image or choosing a new file."
                        : "Drag and drop an image, or browse from your device."}
                    </p>

                    <Button
                      type="button"
                      variant="outline"
                      className="mt-5 rounded-xl bg-background/70"
                      onClick={(event) => {
                        event.stopPropagation();
                        inputRef.current?.click();
                      }}
                      disabled={isProcessing}
                    >
                      <FileImage className="mr-2 h-4 w-4" />
                      {file ? "Replace image" : "Choose image"}
                    </Button>
                  </div>
                </div>

                {file && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-4 flex items-center gap-3 rounded-2xl border border-border bg-background/45 p-3.5"
                  >
                    <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                      <FileImage className="h-5 w-5" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">
                        {file.name}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {(file.size / 1024 / 1024).toFixed(2)} MB · Ready
                      </p>
                    </div>

                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="shrink-0 rounded-xl"
                      onClick={clearSelection}
                      disabled={isProcessing}
                      aria-label="Remove selected receipt"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </motion.div>
                )}

                <Button
                  type="button"
                  className="mt-5 h-12 w-full rounded-xl bg-gradient-pink text-white shadow-glow transition hover:-translate-y-0.5"
                  onClick={handleProcess}
                  disabled={!file || isProcessing}
                >
                  {isProcessing ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Reading receipt and creating batches…
                    </>
                  ) : (
                    <>
                      <ScanLine className="mr-2 h-4 w-4" />
                      Scan and add to pantry
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>

                {isProcessing && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-4 overflow-hidden rounded-2xl border border-primary/25 bg-primary/[0.05] p-4"
                  >
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="flex items-center gap-2 font-semibold text-primary">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Processing receipt
                      </span>
                      <span className="text-muted-foreground">
                        {uploadProgress < 100
                          ? `${uploadProgress}% uploaded`
                          : "AI analysis in progress"}
                      </span>
                    </div>

                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-background/80">
                      <motion.div
                        className="h-full rounded-full bg-gradient-pink"
                        animate={{
                          width:
                            uploadProgress < 100
                              ? `${uploadProgress}%`
                              : "100%",
                        }}
                        transition={{ duration: 0.25 }}
                      />
                    </div>

                    <p className="mt-3 text-xs leading-5 text-muted-foreground">
                      Detailed receipts may take a little longer. Keep this
                      page open while WasteWise creates the pantry batches.
                    </p>
                  </motion.div>
                )}

                <div className="mt-5 grid gap-2 sm:grid-cols-3">
                  <TrustItem
                    icon={ShieldCheck}
                    label="Validated file"
                  />
                  <TrustItem
                    icon={ScanLine}
                    label="AI extraction"
                  />
                  <TrustItem
                    icon={PackageCheck}
                    label="Auto pantry sync"
                  />
                </div>
              </div>

              <div className="border-t border-border/60 bg-background/35 p-5 sm:p-7 lg:p-8 xl:border-l xl:border-t-0">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                      Live preview
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Confirm the image is clear before scanning.
                    </p>
                  </div>

                  <span
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                      previewUrl
                        ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-500"
                        : "border-border bg-card text-muted-foreground",
                    )}
                  >
                    {previewUrl ? "Image selected" : "Waiting for image"}
                  </span>
                </div>

                {previewUrl ? (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="relative overflow-hidden rounded-[26px] border border-border bg-black/20"
                  >
                    <div className="absolute left-4 top-4 z-10 rounded-full border border-white/10 bg-black/60 px-3 py-1 text-[11px] font-medium text-white backdrop-blur">
                      Receipt preview
                    </div>
                    <img
                      src={previewUrl}
                      alt="Receipt preview"
                      className="max-h-[610px] min-h-[420px] w-full object-contain"
                    />
                  </motion.div>
                ) : (
                  <div className="relative grid min-h-[500px] place-items-center overflow-hidden rounded-[26px] border border-dashed border-border bg-card/35 p-8 text-center">
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(236,72,153,0.08),transparent_56%)]" />
                    <div className="relative max-w-xs">
                      <div className="mx-auto grid h-20 w-20 place-items-center rounded-3xl border border-border bg-background/70 text-muted-foreground shadow-sm">
                        <ReceiptText className="h-9 w-9" />
                      </div>
                      <p className="mt-5 text-lg font-semibold">
                        Your receipt will appear here
                      </p>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        Select a JPG, PNG or WEBP image to preview it before
                        processing.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.section>

          {result && (
            <motion.section
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-5"
            >
              <div
                className={cn(
                  "relative overflow-hidden rounded-[26px] border p-5 sm:p-6",
                  hasEdibleItems
                    ? "border-emerald-500/25 bg-emerald-500/[0.06]"
                    : "border-amber-500/25 bg-amber-500/[0.06]",
                )}
              >
                <div
                  className={cn(
                    "pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full blur-3xl",
                    hasEdibleItems
                      ? "bg-emerald-500/10"
                      : "bg-amber-500/10",
                  )}
                />
                <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        "grid h-11 w-11 shrink-0 place-items-center rounded-2xl",
                        hasEdibleItems
                          ? "bg-emerald-500/15 text-emerald-500"
                          : "bg-amber-500/15 text-amber-500",
                      )}
                    >
                      {hasEdibleItems ? (
                        <CheckCircle2 className="h-5 w-5" />
                      ) : (
                        <AlertTriangle className="h-5 w-5" />
                      )}
                    </div>
                    <div>
                      <h3 className="font-semibold sm:text-lg">
                        {hasEdibleItems
                          ? "Receipt processed successfully"
                          : "No edible items found"}
                      </h3>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {hasEdibleItems ? (
                          <>
                            {result.summary.items_created} new batch
                            {result.summary.items_created === 1 ? "" : "es"} added
                            {result.summary.items_skipped > 0
                              ? ` · ${result.summary.items_skipped} skipped`
                              : ""}.
                          </>
                        ) : (
                          <>
                            The receipt was read successfully, but it only
                            contains non-food products. Nothing was added to
                            Smart Pantry.
                          </>
                        )}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {hasEdibleItems && (
                      <Button
                        asChild
                        className="rounded-xl bg-gradient-pink text-white"
                      >
                        <Link to="/pantry">
                          Open Smart Pantry
                          <ArrowRight className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      className="rounded-xl"
                      onClick={clearSelection}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Scan another
                    </Button>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <SummaryCard
                  icon={Store}
                  label="Merchant"
                  value={
                    result.receipt.merchant_name ??
                    "Unknown merchant"
                  }
                  tone="primary"
                />
                <SummaryCard
                  icon={CalendarDays}
                  label="Purchase date"
                  value={formatDate(
                    result.receipt.purchase_date,
                  )}
                  note={
                    result.receipt.purchase_date_source ===
                    "upload_date"
                      ? "Upload date used"
                      : "Read from receipt"
                  }
                  tone="default"
                />
                <SummaryCard
                  icon={WalletCards}
                  label="Receipt total"
                  value={formatMoney(
                    result.receipt.total_amount,
                    result.receipt.currency,
                  )}
                  tone="warning"
                />
                <SummaryCard
                  icon={
                    hasEdibleItems
                      ? PackageCheck
                      : AlertTriangle
                  }
                  label={
                    hasEdibleItems
                      ? "New batches"
                      : "Pantry items"
                  }
                  value={`${result.summary.items_created}`}
                  note={
                    hasEdibleItems
                      ? `${result.summary.items_skipped} skipped`
                      : "Nothing added"
                  }
                  tone={
                    hasEdibleItems
                      ? "success"
                      : "warning"
                  }
                />
              </div>

              <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
                <div className="rounded-[28px] border border-border bg-card p-5 sm:p-6">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
                        Receipt contents
                      </p>
                      <h3 className="mt-2 text-lg font-semibold">
                        Extracted products
                      </h3>
                      <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                        Pantry-friendly names are shown first. The original
                        receipt name stays visible underneath for reference.
                      </p>
                    </div>
                    <div className="rounded-2xl bg-primary/10 p-3 text-primary">
                      <ReceiptText className="h-5 w-5" />
                    </div>
                  </div>

                  <div className="mt-5 grid gap-3 lg:grid-cols-2">
                    {result.receipt.items.map((item, index) => (
                      <motion.article
                        key={`${item.raw_name}-${index}`}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(index * 0.03, 0.24) }}
                        className="rounded-2xl border border-border/70 bg-background/35 p-4 transition hover:border-primary/30"
                      >
                        <div className="flex items-start gap-3">
                          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                            <Package className="h-[18px] w-[18px]" />
                          </div>

                          <div className="min-w-0 flex-1">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate font-semibold">
                                  {item.pantry_name ??
                                    item.product_name}
                                </p>
                                <p className="mt-1 truncate text-xs text-muted-foreground">
                                  Receipt: {item.product_name}
                                </p>
                              </div>
                              <p className="shrink-0 text-sm font-semibold tabular-nums">
                                {formatMoney(
                                  item.line_total,
                                  result.receipt.currency,
                                )}
                              </p>
                            </div>

                            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                              <InfoPill>
                                Qty {formatPurchasedQuantity(item)}
                              </InfoPill>
                              <InfoPill>
                                {formatPackage(item)}
                              </InfoPill>
                              <InfoPill className="capitalize">
                                {item.category}
                              </InfoPill>
                              <InfoPill className="capitalize">
                                {item.location}
                              </InfoPill>
                            </div>
                          </div>
                        </div>
                      </motion.article>
                    ))}
                  </div>
                </div>

                <div className="space-y-5">
                  <FinancialCard result={result} />

                  <div className="rounded-[28px] border border-border bg-card p-5 sm:p-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
                          Pantry sync
                        </p>
                        <h3 className="mt-2 font-semibold">
                          {hasEdibleItems
                            ? "Batches created"
                            : "No pantry batches created"}
                        </h3>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">
                          {hasEdibleItems
                            ? "Every edible purchase keeps its own quantity, purchase date and expiry date."
                            : "Non-food products are ignored and are not added to Smart Pantry."}
                        </p>
                      </div>
                      <div
                        className={cn(
                          "rounded-2xl p-3",
                          hasEdibleItems
                            ? "bg-primary/10 text-primary"
                            : "bg-amber-500/10 text-amber-500",
                        )}
                      >
                        {hasEdibleItems ? (
                          <PackageCheck className="h-5 w-5" />
                        ) : (
                          <AlertTriangle className="h-5 w-5" />
                        )}
                      </div>
                    </div>

                    {hasEdibleItems ? (
                      <div className="mt-5 max-h-[520px] space-y-3 overflow-y-auto pr-1">
                        {result.pantry_changes.map((change, index) => (
                          <div
                            key={`${
                              change.pantry_item_id ??
                              change.product_name
                            }-${index}`}
                            className="rounded-2xl border border-border/70 bg-background/35 p-4"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold">
                                  {change.product_name}
                                </p>
                                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                  {formatChangeQuantity(change)} · Expires {formatDate(change.expiry_date)}
                                </p>
                              </div>

                              <span
                                className={cn(
                                  "shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold capitalize",
                                  change.action === "created"
                                    ? "bg-emerald-500/10 text-emerald-500"
                                    : change.action === "skipped"
                                      ? "bg-amber-500/10 text-amber-500"
                                      : "bg-primary/10 text-primary",
                                )}
                              >
                                {change.action === "created"
                                  ? "New batch"
                                  : change.action}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-5 rounded-2xl border border-amber-500/20 bg-amber-500/[0.05] p-5 text-center">
                        <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-amber-500/10 text-amber-500">
                          <Package className="h-5 w-5" />
                        </div>
                        <p className="mt-3 text-sm font-semibold">
                          Nothing added to Smart Pantry
                        </p>
                        <p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
                          WasteWise found receipt products, but none of them
                          were edible pantry items.
                        </p>
                      </div>
                    )}

                    <div
                      className={cn(
                        "mt-5 grid gap-2",
                        hasEdibleItems &&
                          "sm:grid-cols-2 xl:grid-cols-1",
                      )}
                    >
                      {hasEdibleItems && (
                        <Button
                          asChild
                          className="rounded-xl bg-gradient-pink text-white"
                        >
                          <Link to="/pantry">
                            Open Smart Pantry
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </Link>
                        </Button>
                      )}
                      <Button
                        type="button"
                        variant="outline"
                        className="rounded-xl"
                        onClick={clearSelection}
                      >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        Scan another receipt
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </motion.section>
          )}
        </div>
      </AppShell>
    </RequireAuth>
  );
}

function ProcessStep({
  number,
  icon: Icon,
  label,
}: {
  number: string;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-background/40 p-3 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <span className="text-[10px] font-bold tracking-widest text-muted-foreground/70">
          {number}
        </span>
      </div>
      <p className="mt-3 text-xs font-semibold sm:text-sm">
        {label}
      </p>
    </div>
  );
}

function TrustItem({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div className="flex items-center justify-center gap-2 rounded-xl border border-border/70 bg-background/35 px-3 py-2.5 text-xs text-muted-foreground">
      <Icon className="h-3.5 w-3.5 text-primary" />
      {label}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  note,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  note?: string;
  tone: "default" | "primary" | "warning" | "success";
}) {
  const toneClasses =
    tone === "primary"
      ? "bg-primary/10 text-primary"
      : tone === "warning"
        ? "bg-amber-500/10 text-amber-500"
        : tone === "success"
          ? "bg-emerald-500/10 text-emerald-500"
          : "bg-card-elevated text-foreground";

  return (
    <motion.div
      whileHover={{ y: -3 }}
      className="rounded-2xl border border-border bg-card p-4 transition hover:border-primary/25 sm:p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {label}
          </p>
          <p className="mt-3 truncate text-lg font-semibold">
            {value}
          </p>
          {note && (
            <p className="mt-1 text-xs text-muted-foreground">
              {note}
            </p>
          )}
        </div>
        <div
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-xl",
            toneClasses,
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </div>
      </div>
    </motion.div>
  );
}

function InfoPill({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "rounded-full border border-border/70 bg-card px-2.5 py-1",
        className,
      )}
    >
      {children}
    </span>
  );
}

function FinancialCard({
  result,
}: {
  result: ReceiptProcessResponse;
}) {
  const validation = result.financial_validation;
  const reconciled =
    validation.status === "reconciled";
  const unavailable =
    validation.status === "unavailable";

  return (
    <div className="rounded-[28px] border border-border bg-card p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Validation
          </p>
          <h3 className="mt-2 font-semibold">
            Financial check
          </h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Product lines, tax, charges and the receipt total are compared.
          </p>
        </div>

        <div
          className={cn(
            "grid h-11 w-11 shrink-0 place-items-center rounded-2xl",
            reconciled
              ? "bg-emerald-500/10 text-emerald-500"
              : unavailable
                ? "bg-muted text-muted-foreground"
                : "bg-amber-500/10 text-amber-500",
          )}
        >
          {reconciled ? (
            <CheckCircle2 className="h-5 w-5" />
          ) : (
            <AlertTriangle className="h-5 w-5" />
          )}
        </div>
      </div>

      <div className="mt-5 overflow-hidden rounded-2xl border border-border/70 bg-background/35">
        <MoneyRow
          label="Items subtotal"
          value={formatMoney(
            validation.items_subtotal,
            result.receipt.currency,
          )}
        />
        <MoneyRow
          label="Tax"
          value={formatMoney(
            result.receipt.tax_amount,
            result.receipt.currency,
          )}
        />
        <MoneyRow
          label="Calculated total"
          value={formatMoney(
            validation.calculated_total,
            result.receipt.currency,
          )}
        />
        <MoneyRow
          label="Receipt total"
          value={formatMoney(
            validation.receipt_total,
            result.receipt.currency,
          )}
          strong
          last
        />
      </div>

      <div
        className={cn(
          "mt-4 rounded-2xl border p-3.5 text-xs leading-5",
          reconciled
            ? "border-emerald-500/20 bg-emerald-500/[0.05] text-emerald-500"
            : unavailable
              ? "border-border bg-muted/30 text-muted-foreground"
              : "border-amber-500/20 bg-amber-500/[0.05] text-amber-500",
        )}
      >
        {validation.notes[0] ??
          "No financial validation note was returned."}
      </div>
    </div>
  );
}

function MoneyRow({
  label,
  value,
  strong = false,
  last = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
  last?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-4 py-3 text-sm",
        !last && "border-b border-border/70",
        strong && "bg-card/60",
      )}
    >
      <span className="text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums",
          strong && "font-semibold text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}