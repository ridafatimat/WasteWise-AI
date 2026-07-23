import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Home,
  Leaf,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";
import { useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { register as apiRegister } from "@/services/api";
import { extractApiError, parseFieldErrors } from "@/services/api/client";

export const Route = createFileRoute("/register")({
  head: () => ({
    meta: [
      { title: "Create account — WasteWise AI" },
      {
        name: "description",
        content: "Create a WasteWise AI household account.",
      },
    ],
  }),
  component: RegisterPage,
});

const BENEFITS = [
  "Track pantry batches and expiry dates",
  "Get AI-powered grocery and recipe suggestions",
  "Understand your household waste patterns",
];


function BrandMark() {
  return (
    <Link to="/" className="inline-flex items-center gap-3">
      <div className="relative grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-[#ff2d8f] via-[#f72585] to-[#ff69b4] text-white shadow-[0_12px_35px_rgba(247,37,133,0.32)]">
        <Leaf className="h-5 w-5" />
        <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-[#0a0a0d] bg-emerald-400" />
      </div>

      <div>
        <div className="text-base font-extrabold tracking-tight text-white">
          WasteWise
        </div>
        <div className="text-[10px] font-bold uppercase tracking-[0.24em] text-[#ff4ca0]">
          AI Pantry
        </div>
      </div>
    </Link>
  );
}

function RegisterPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    household_name: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const set =
    (key: keyof typeof form) => (event: ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;

      setForm((current) => ({
        ...current,
        [key]: value,
      }));

      if (fieldErrors[key]) {
        setFieldErrors((current) => {
          const next = { ...current };
          delete next[key];
          return next;
        });
      }
    };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setFieldErrors({});
    setLoading(true);

    try {
      await apiRegister({
        name: form.name.trim(),
        email: form.email.trim(),
        password: form.password,
        household_name:
          form.household_name.trim(),
      });

      try {
        await login(form.email, form.password);
        navigate({ to: "/dashboard" });
      } catch {
        navigate({ to: "/login" });
      }
    } catch (err) {
      setFieldErrors(parseFieldErrors(err));
      setError(extractApiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#08080a] text-white">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-[12%] top-[-16rem] h-[34rem] w-[34rem] rounded-full bg-[#f72585]/15 blur-[130px]" />
        <div className="absolute bottom-[-16rem] right-[-10rem] h-[34rem] w-[34rem] rounded-full bg-violet-500/10 blur-[140px]" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.018)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.018)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:linear-gradient(to_bottom,black,transparent_88%)]" />
      </div>

      <div className="relative z-10 grid min-h-screen lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden border-r border-white/[0.07] p-10 lg:flex lg:flex-col lg:justify-between xl:p-14">
          <BrandMark />

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55 }}
            className="max-w-xl"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-[#f72585]/20 bg-[#f72585]/10 px-3 py-1 text-xs font-semibold text-[#ff64ae]">
              <Sparkles className="h-3.5 w-3.5" />
              Smarter food management starts here
            </div>

            <h1 className="mt-6 text-5xl font-black leading-[1.05] tracking-[-0.045em] xl:text-6xl">
              Build a pantry that
              <span className="block bg-gradient-to-r from-[#ff4ca0] to-[#ff85be] bg-clip-text text-transparent">
                thinks ahead.
              </span>
            </h1>

            <p className="mt-5 max-w-lg text-base leading-8 text-white/50">
              Create your household account and let WasteWise help you track,
              plan, rescue, and reduce food waste.
            </p>

            <div className="mt-9 space-y-4">
              {BENEFITS.map((benefit) => (
                <div key={benefit} className="flex items-center gap-3 text-sm text-white/72">
                  <div className="grid h-7 w-7 place-items-center rounded-full border border-emerald-400/20 bg-emerald-400/10 text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" />
                  </div>
                  {benefit}
                </div>
              ))}
            </div>
          </motion.div>

          <div className="flex items-center gap-2 text-xs text-white/35">
            <ShieldCheck className="h-4 w-4 text-emerald-400/70" />
            Your household data stays private and secure
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-4 py-8 sm:px-8 lg:px-12">
          <div className="w-full max-w-lg">
            <div className="mb-8 flex items-center justify-between lg:hidden">
              <BrandMark />
              <Link
                to="/"
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.035] text-white/60 transition hover:text-white"
                aria-label="Back to home"
              >
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </div>

            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.08 }}
              className="rounded-[2rem] border border-white/[0.09] bg-[#121216]/82 p-5 shadow-[0_35px_100px_rgba(0,0,0,0.42)] backdrop-blur-2xl sm:p-8"
            >
              <div className="hidden lg:block">
                <Link
                  to="/"
                  className="inline-flex items-center gap-2 text-xs font-semibold text-white/45 transition hover:text-white"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back to home
                </Link>
              </div>

              <div className="mt-2 lg:mt-8">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.035] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/45">
                  Household setup
                </div>

                <h2 className="mt-4 text-3xl font-black tracking-[-0.035em]">
                  Start using WasteWise
                </h2>

                <p className="mt-2 text-sm leading-6 text-white/45">
                  Enter your household name. If it already exists, you will join it; otherwise WasteWise will create it for you.
                </p>
              </div>

              <form onSubmit={onSubmit} className="mt-8 space-y-5">
                <FormField
                  id="name"
                  label="Your name"
                  icon={User}
                  error={fieldErrors.name}
                >
                  <Input
                    id="name"
                    type="text"
                    autoComplete="name"
                    required
                    value={form.name}
                    onChange={set("name")}
                    placeholder="Alex"
                    className="h-12 rounded-xl border-white/10 bg-black/25 pl-10 text-white placeholder:text-white/25 focus-visible:ring-[#f72585]/35"
                  />
                </FormField>

                <FormField
                  id="household_name"
                  label="Household name"
                  icon={Home}
                  error={fieldErrors.household_name}
                >
                  <Input
                    id="household_name"
                    type="text"
                    required
                    value={form.household_name}
                    onChange={set("household_name")}
                    placeholder="Rida's House"
                    className="h-12 rounded-xl border-white/10 bg-black/25 pl-10 text-white placeholder:text-white/25 focus-visible:ring-[#f72585]/35"
                  />
                </FormField>

                <p className="-mt-2 text-xs leading-5 text-white/35">
                  Existing household name: join as a member. New household
                  name: create it as the owner.
                </p>

                <FormField
                  id="email"
                  label="Email address"
                  icon={Mail}
                  error={fieldErrors.email}
                >
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={form.email}
                    onChange={set("email")}
                    placeholder="user@example.com"
                    className="h-12 rounded-xl border-white/10 bg-black/25 pl-10 text-white placeholder:text-white/25 focus-visible:ring-[#f72585]/35"
                  />
                </FormField>

                <FormField
                  id="password"
                  label="Password"
                  icon={LockKeyhole}
                  error={fieldErrors.password}
                >
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    required
                    value={form.password}
                    onChange={set("password")}
                    placeholder="••••••••"
                    className="h-12 rounded-xl border-white/10 bg-black/25 px-10 text-white placeholder:text-white/25 focus-visible:ring-[#f72585]/35"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-white/35 transition hover:text-white"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </FormField>

                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-xl border border-[#ff4d6d]/25 bg-[#ff4d6d]/10 px-3.5 py-3 text-sm text-[#ff7c93]"
                  >
                    {error}
                  </motion.div>
                )}

                <Button
                  type="submit"
                  disabled={loading}
                  className="h-12 w-full rounded-xl bg-gradient-to-r from-[#f72585] to-[#ff4ca0] text-sm font-bold text-white shadow-[0_14px_40px_rgba(247,37,133,0.25)] transition hover:-translate-y-0.5 hover:opacity-100 hover:shadow-[0_18px_48px_rgba(247,37,133,0.34)]"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Creating account…
                    </>
                  ) : (
                    <>
                      Create account
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>
              </form>

              <div className="mt-7 border-t border-white/[0.07] pt-6 text-center text-sm text-white/45">
                Already have an account?{" "}
                <Link
                  to="/login"
                  className="font-semibold text-[#ff4ca0] transition hover:text-[#ff78b7]"
                >
                  Sign in
                </Link>
              </div>
            </motion.div>
          </div>
        </section>
      </div>
    </main>
  );
}

function FormField({
  id,
  label,
  icon: Icon,
  error,
  children,
}: {
  id: string;
  label: string;
  icon: typeof User;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <Label htmlFor={id} className="text-xs font-semibold text-white/65">
        {label}
      </Label>
      <div className="relative mt-2">
        <Icon className="pointer-events-none absolute left-3.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-white/30" />
        {children}
      </div>
      {error && <p className="mt-1.5 text-xs text-[#ff7c93]">{error}</p>}
    </div>
  );
}