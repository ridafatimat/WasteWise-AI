import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Package,
  Plus,
  Receipt,
  ShieldAlert,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { ErrorMessage } from "@/components/ErrorMessage";
import { RequireAuth } from "@/components/RequireAuth";
import { daysUntil, formatDate } from "@/lib/format";
import { listPantryItems, getWasteRisk } from "@/services/api";
import { extractApiError } from "@/services/api/client";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      {
        title: "Dashboard — WasteWise AI",
      },
    ],
  }),

  component: () => (
    <RequireAuth>
      <AppShell title="Dashboard">
        <DashboardView />
      </AppShell>
    </RequireAuth>
  ),
});

type DashboardPath = "/pantry" | "/rescue-mode" | "/receipts" | "/recipes";

type Tone = "neutral" | "warning" | "danger" | "primary";

const cardMotion = {
  hidden: { opacity: 0, y: 18 },
  visible: (index: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.42,
      delay: index * 0.06,
      ease: [0.22, 1, 0.36, 1] as const,
    },
  }),
};

function useCounter(target: number, ms = 700) {
  const [number, setNumber] = useState(0);

  useEffect(() => {
    const start = performance.now();
    let animationFrame = 0;

    const step = (time: number) => {
      const progress = Math.min(1, (time - start) / ms);

      setNumber(Math.round(target * (1 - Math.pow(1 - progress, 3))));

      if (progress < 1) {
        animationFrame = requestAnimationFrame(step);
      }
    };

    animationFrame = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(animationFrame);
    };
  }, [target, ms]);

  return number;
}

function DashboardView() {
  const pantry = useQuery({
    queryKey: ["pantry"],
    queryFn: listPantryItems,
    retry: 0,
    staleTime: 0,
    refetchOnMount: "always",
  });

  const risks = useQuery({
    queryKey: ["risks"],
    queryFn: getWasteRisk,
    retry: 0,
    staleTime: 0,
    refetchOnMount: "always",
  });

  const allItems = pantry.data ?? [];

  /*
   * Dashboard must only use currently usable stock.
   * Wasted, consumed, expired, zero-quantity, and past-expiry batches
   * remain available in History but must not appear here.
   */
  const items = allItems.filter((item) => {
    const status = (item.status || "")
      .trim()
      .toLowerCase();

    const remaining = Number(
      item.quantity_remaining ??
      item.quantity ??
      item.quantity_initial ??
      0,
    );

    const days = daysUntil(
      item.expiry_date,
    );

    const isClosed =
      status === "consumed" ||
      status === "wasted" ||
      status === "expired";

    const hasNoStock =
      !Number.isFinite(remaining) ||
      remaining <= 0;

    const isPastExpiry =
      days !== null &&
      days !== undefined &&
      days < 0;

    return (
      !isClosed &&
      !hasNoStock &&
      !isPastExpiry
    );
  });

  const expiringSoon = items.filter((item) => {
    const days = daysUntil(item.expiry_date);

    return days !== null && days !== undefined && days >= 0 && days <= 3;
  });

  /*
   * IMPORTANT: this is the existing nearest-expiry logic.
   * It intentionally shows every item tied on the earliest upcoming date,
   * and hides items expiring later.
   */
  const upcomingExpiryItems = items
    .map((item) => ({
      item,
      days: daysUntil(item.expiry_date),
    }))
    .filter(
      (
        entry,
      ): entry is {
        item: (typeof items)[number];
        days: number;
      } => entry.days !== null && entry.days !== undefined && entry.days >= 0,
    );

  const nearestExpiryDays =
    upcomingExpiryItems.length > 0
      ? Math.min(...upcomingExpiryItems.map((entry) => entry.days))
      : null;

  const earliestExpiring =
    nearestExpiryDays === null
      ? []
      : upcomingExpiryItems
          .filter((entry) => entry.days === nearestExpiryDays)
          .map((entry) => entry.item)
          .sort((firstItem, secondItem) =>
            firstItem.product_name.localeCompare(secondItem.product_name),
          );

  const activeItemIds = new Set(
    items.map((item) => item.id),
  );

  const riskItems = [
    ...(risks.data ?? []),
  ]
    .filter((risk) =>
      activeItemIds.has(
        risk.pantry_item_id,
      ),
    )
    .sort(
      (firstRisk, secondRisk) =>
        secondRisk.risk_score -
        firstRisk.risk_score,
    );

  const highRisk = riskItems.filter(
    (risk) => (risk.risk_band || "").toLowerCase() === "high",
  ).length;

  const recentlyAdded = [...items]
    .sort((firstItem, secondItem) =>
      (secondItem.created_at || "").localeCompare(firstItem.created_at || ""),
    )
    .slice(0, 5);

  const totalCount = useCounter(items.length);
  const expiringCount = useCounter(expiringSoon.length);
  const highRiskCount = useCounter(highRisk);
  const recentlyAddedCount = useCounter(recentlyAdded.length);

  const error = pantry.error || risks.error;

  const attentionDescription =
    nearestExpiryDays === null
      ? "No upcoming expiry dates."
      : nearestExpiryDays === 0
        ? "Every item shown below expires today."
        : nearestExpiryDays === 1
          ? "Every item shown below expires tomorrow."
          : `Every item shown below expires in ${nearestExpiryDays} days.`;

  const nearestExpiryLabel =
    nearestExpiryDays === null
      ? "All clear"
      : nearestExpiryDays === 0
        ? "Today"
        : nearestExpiryDays === 1
          ? "Tomorrow"
          : `${nearestExpiryDays} days`;

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-8">
      <motion.section
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{
          duration: 0.5,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="relative isolate overflow-hidden rounded-[30px] border border-primary/25 bg-gradient-to-br from-primary/20 via-card to-card p-5 shadow-[0_24px_80px_-48px_hsl(var(--primary))] sm:p-7 lg:p-8"
      >
        <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-primary/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 left-1/3 h-64 w-64 rounded-full bg-violet-500/10 blur-3xl" />

        <div className="relative grid gap-7 lg:grid-cols-[1fr_auto] lg:items-center">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              Smart pantry overview
            </div>

            <h1 className="mt-5 max-w-2xl text-3xl font-bold tracking-[-0.035em] sm:text-4xl lg:text-[44px] lg:leading-[1.08]">
              Your pantry,
              <span className="bg-gradient-to-r from-primary via-pink-400 to-fuchsia-400 bg-clip-text text-transparent">
                {" "}
                one step ahead.
              </span>
            </h1>

            <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
              See what needs attention, move faster on urgent food, and keep the
              whole household organised from one place.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                to="/rescue-mode"
                className="group inline-flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-primary to-pink-500 px-4 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition hover:-translate-y-0.5 hover:shadow-primary/30"
              >
                <ShieldAlert className="h-4 w-4" />
                Open Rescue Mode
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>

              <Link
                to="/pantry"
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-border/80 bg-background/50 px-4 text-sm font-semibold backdrop-blur transition hover:border-primary/40 hover:bg-primary/5"
              >
                <Package className="h-4 w-4 text-primary" />
                View pantry
              </Link>
            </div>
          </div>

          <div className="min-w-[250px] rounded-3xl border border-white/10 bg-background/55 p-5 shadow-2xl backdrop-blur-xl lg:min-w-[280px]">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  Next expiry
                </p>
                <p className="mt-2 text-3xl font-bold tracking-tight">
                  {nearestExpiryLabel}
                </p>
              </div>

              <div className="grid h-14 w-14 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                <Clock3 className="h-6 w-6" />
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between rounded-2xl border border-border/60 bg-card/70 px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Earliest batch
              </div>

              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
                {earliestExpiring.length} item
                {earliestExpiring.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>
        </div>
      </motion.section>

      {error && (
        <ErrorMessage
          message={extractApiError(error)}
          onRetry={() => {
            pantry.refetch();
            risks.refetch();
          }}
        />
      )}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          index={0}
          icon={Package}
          eyebrow="Inventory"
          label="Active pantry items"
          value={totalCount}
          tone="neutral"
        />

        <StatCard
          index={1}
          icon={CalendarClock}
          eyebrow="Next 3 days"
          label="Expiring soon"
          value={expiringCount}
          tone="warning"
        />

        <StatCard
          index={2}
          icon={ShieldAlert}
          eyebrow="Prediction"
          label="High-risk items"
          value={highRiskCount}
          tone="danger"
        />

        <StatCard
          index={3}
          icon={Sparkles}
          eyebrow="Latest activity"
          label="Recently added"
          value={recentlyAddedCount}
          tone="primary"
        />
      </section>

      <section className="rounded-[28px] border border-border/70 bg-card/65 p-4 shadow-sm backdrop-blur sm:p-5">
        <div className="mb-4 flex items-end justify-between gap-4 px-1">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              Quick access
            </p>
            <h2 className="mt-1 text-lg font-semibold tracking-tight">
              What would you like to do?
            </h2>
          </div>

          <span className="hidden text-xs text-muted-foreground sm:block">
            Your most-used WasteWise tools
          </span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <QuickAction
            index={0}
            to="/pantry"
            icon={Plus}
            label="Add pantry item"
            description="Add food manually"
            primary
          />

          <QuickAction
            index={1}
            to="/rescue-mode"
            icon={ShieldAlert}
            label="Rescue Mode"
            description="Act on urgent food"
          />

          <QuickAction
            index={2}
            to="/receipts"
            icon={Receipt}
            label="Scan a receipt"
            description="Update pantry with AI"
          />

          <QuickAction
            index={3}
            to="/recipes"
            icon={Sparkles}
            label="Find recipes"
            description="Use food before expiry"
          />
        </div>
      </section>

      <motion.section
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{
          duration: 0.45,
          delay: 0.18,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="overflow-hidden rounded-[28px] border border-border/70 bg-card/70 shadow-sm"
      >
        <div className="flex flex-col gap-4 border-b border-border/60 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="flex items-start gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
              <CalendarClock className="h-5 w-5" />
            </div>

            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold tracking-tight">
                  Items needing attention
                </h2>

                {earliestExpiring.length > 0 && (
                  <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-bold text-primary">
                    {earliestExpiring.length} earliest
                  </span>
                )}
              </div>

              <p className="mt-1 text-sm text-muted-foreground">
                {attentionDescription}
              </p>
            </div>
          </div>

          <Link
            to="/pantry"
            className="group inline-flex items-center gap-2 text-sm font-semibold text-muted-foreground transition hover:text-primary"
          >
            Full pantry
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>

        <div className="p-4 sm:p-5">
          {pantry.isLoading ? (
            <SkeletonGrid />
          ) : earliestExpiring.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/80 bg-background/30 p-4">
              <EmptyState
                icon={CalendarClock}
                title="No upcoming expiry dates"
                description="Add expiry dates to pantry items to see what should be used first."
              />
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {earliestExpiring.map((item, index) => {
                const days = daysUntil(item.expiry_date);
                const urgent = days === 0;

                return (
                  <motion.div
                    key={item.id}
                    variants={cardMotion}
                    initial="hidden"
                    animate="visible"
                    custom={index}
                  >
                    <Link
                      to="/pantry/$id"
                      params={{
                        id: item.id,
                      }}
                      className="group flex min-h-[92px] items-center gap-4 rounded-2xl border border-border/70 bg-background/35 p-4 transition duration-300 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary/[0.045] hover:shadow-lg hover:shadow-primary/5"
                    >
                      <div
                        className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border ${
                          urgent
                            ? "border-red-500/25 bg-red-500/10 text-red-400"
                            : "border-amber-500/25 bg-amber-500/10 text-amber-400"
                        }`}
                      >
                        <Package className="h-5 w-5" />
                      </div>

                      <div className="min-w-0 flex-1">
                        <p className="truncate font-semibold tracking-tight transition group-hover:text-primary">
                          {item.product_name}
                        </p>

                        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                          <span>{formatDate(item.expiry_date)}</span>
                          <span className="h-1 w-1 rounded-full bg-muted-foreground/50" />
                          <span className="capitalize">
                            {item.storage_location || "Not set"}
                          </span>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-3">
                        <span
                          className={`rounded-full px-3 py-1.5 text-xs font-bold ${
                            urgent
                              ? "bg-red-500/10 text-red-400"
                              : "bg-amber-500/10 text-amber-400"
                          }`}
                        >
                          {days === 0
                            ? "Today"
                            : days === 1
                              ? "Tomorrow"
                              : `${days}d left`}
                        </span>

                        <ArrowRight className="hidden h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary sm:block" />
                      </div>
                    </Link>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>
      </motion.section>
    </div>
  );
}

function StatCard({
  index,
  icon: Icon,
  eyebrow,
  label,
  value,
  tone,
}: {
  index: number;
  icon: LucideIcon;
  eyebrow: string;
  label: string;
  value: number;
  tone: Tone;
}) {
  const styles: Record<
    Tone,
    {
      icon: string;
      glow: string;
      line: string;
    }
  > = {
    neutral: {
      icon: "border-white/10 bg-white/5 text-foreground",
      glow: "bg-white/5",
      line: "from-white/60 to-transparent",
    },
    warning: {
      icon: "border-amber-500/20 bg-amber-500/10 text-amber-400",
      glow: "bg-amber-500/10",
      line: "from-amber-400 to-transparent",
    },
    danger: {
      icon: "border-red-500/20 bg-red-500/10 text-red-400",
      glow: "bg-red-500/10",
      line: "from-red-400 to-transparent",
    },
    primary: {
      icon: "border-primary/20 bg-primary/10 text-primary",
      glow: "bg-primary/10",
      line: "from-primary to-transparent",
    },
  };

  const style = styles[tone];

  return (
    <motion.article
      variants={cardMotion}
      initial="hidden"
      animate="visible"
      custom={index}
      whileHover={{ y: -4 }}
      className="group relative isolate overflow-hidden rounded-[24px] border border-border/70 bg-card/75 p-5 shadow-sm transition hover:border-primary/25 hover:shadow-xl hover:shadow-black/10"
    >
      <div
        className={`pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full blur-3xl transition group-hover:scale-125 ${style.glow}`}
      />

      <div className="relative flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.17em] text-muted-foreground">
            {eyebrow}
          </p>
          <p className="mt-3 text-4xl font-bold tracking-[-0.04em] tabular-nums">
            {value}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{label}</p>
        </div>

        <div
          className={`grid h-11 w-11 place-items-center rounded-2xl border ${style.icon}`}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>

      <div className="relative mt-5 h-px overflow-hidden bg-border/60">
        <div className={`h-full w-2/3 bg-gradient-to-r ${style.line}`} />
      </div>
    </motion.article>
  );
}

function QuickAction({
  index,
  to,
  icon: Icon,
  label,
  description,
  primary = false,
}: {
  index: number;
  to: DashboardPath;
  icon: LucideIcon;
  label: string;
  description: string;
  primary?: boolean;
}) {
  return (
    <motion.div
      variants={cardMotion}
      initial="hidden"
      animate="visible"
      custom={index}
    >
      <Link
        to={to}
        className={`group flex min-h-[92px] items-center gap-3 rounded-2xl border p-3.5 transition duration-300 hover:-translate-y-0.5 ${
          primary
            ? "border-primary/35 bg-gradient-to-br from-primary/20 via-primary/10 to-transparent shadow-lg shadow-primary/5 hover:border-primary/60"
            : "border-border/70 bg-background/35 hover:border-primary/30 hover:bg-primary/[0.04]"
        }`}
      >
        <div
          className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border transition group-hover:scale-105 ${
            primary
              ? "border-primary/30 bg-gradient-to-br from-primary to-pink-500 text-white shadow-lg shadow-primary/25"
              : "border-primary/20 bg-primary/10 text-primary"
          }`}
        >
          <Icon className="h-5 w-5" />
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{label}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {description}
          </p>
        </div>

        <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
      </Link>
    </motion.div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {[0, 1, 2, 3].map((item) => (
        <div
          key={item}
          className="h-[92px] animate-pulse rounded-2xl border border-border/70 bg-background/40"
        />
      ))}
    </div>
  );
}