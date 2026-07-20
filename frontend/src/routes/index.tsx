import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Bookmark,
  BrainCircuit,
  CalendarClock,
  Check,
  ChefHat,
  Leaf,
  Package,
  Receipt,
  Share2,
  ShieldAlert,
  ShoppingBasket,
  Sparkles,
  Target,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";

import { WasteWiseLogo } from "@/components/WasteWiseLogo";
import { PublicFooter } from "@/components/PublicFooter";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      {
        title:
          "WasteWise AI — Waste less. Save more. Use what you already have.",
      },
      {
        name: "description",
        content:
          "Track pantry items, monitor expiry dates, and let AI predict which groceries are most at risk of going to waste.",
      },
    ],
  }),
  component: Landing,
});

type Feature = {
  icon: LucideIcon;
  title: string;
  desc: string;
};

type AboutItem = {
  icon: LucideIcon;
  title: string;
  desc: string;
};

const features: Feature[] = [
  {
    icon: Users,
    title: "Household Profile",
    desc: "Set up your household and manage pantry activity from one shared account.",
  },
  {
    icon: Package,
    title: "Smart Pantry",
    desc: "Add groceries, update quantities, edit expiry dates, and keep your inventory accurate.",
  },
  {
    icon: Receipt,
    title: "Receipt Upload & OCR",
    desc: "Upload a receipt and review the extracted items before adding them to your pantry.",
  },
  {
    icon: CalendarClock,
    title: "Expiry Tracking",
    desc: "See what is expiring today, this week, and later through clear visual cues.",
  },
  {
    icon: Trash2,
    title: "Waste Logging",
    desc: "Record consumed, wasted, expired, or adjusted quantities for each pantry item.",
  },
  {
    icon: ShieldAlert,
    title: "Waste-Risk Prediction",
    desc: "See which products are most likely to go unused and understand exactly why.",
  },
  {
    icon: ShoppingBasket,
    title: "Grocery Recommendations",
    desc: "Get shopping suggestions based on stock levels and household consumption patterns.",
  },
  {
    icon: ChefHat,
    title: "Recipe Suggestions",
    desc: "Discover recipes that prioritise ingredients approaching their expiry date.",
  },
];

const aboutItems: AboutItem[] = [
  {
    icon: Target,
    title: "Our Goal",
    desc: "Help households prevent avoidable food waste through better visibility and timely actions.",
  },
  {
    icon: BrainCircuit,
    title: "Smart Technology",
    desc: "Combine receipt OCR, pantry information, expiry rules, and machine-learning predictions.",
  },
  {
    icon: Leaf,
    title: "Sustainable Habits",
    desc: "Turn everyday pantry management into a simpler and more sustainable household routine.",
  },
];

function Landing() {
  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <Navbar />

      <main>
        <Hero />
        <Features />
        <About />
        <ContactCTA />
      </main>

      <PublicFooter />
    </div>
  );
}

function Navbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link
          to="/"
          aria-label="WasteWise AI home"
          className="rounded-xl outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-primary"
        >
          <WasteWiseLogo />
        </Link>

        <nav
          aria-label="Main navigation"
          className="hidden items-center gap-8 md:flex"
        >
          <a
            href="#features"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Features
          </a>

          <a
            href="#about"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            About
          </a>

          <a
            href="#contact"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Contact
          </a>
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          <Link to="/login">
            <Button
              variant="ghost"
              className="font-semibold text-foreground hover:text-primary"
            >
              Login
            </Button>
          </Link>

          <Link to="/register">
            <Button className="bg-gradient-pink font-semibold text-white shadow-glow hover:opacity-95">
              Register
            </Button>
          </Link>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-border/60">
      <div className="absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-0 h-[500px] w-[900px] -translate-x-1/2 bg-radial-pink opacity-60" />

        <div className="animate-float absolute right-[8%] top-[15%] h-72 w-72 rounded-full bg-primary/15 blur-3xl" />

        <div className="animate-float absolute bottom-[10%] left-[6%] h-64 w-64 rounded-full bg-primary-bright/10 blur-3xl" />
      </div>

      <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_1.05fr] lg:gap-10 lg:py-20">
        {/* Left: copy */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center lg:text-left"
        >
          <div className="mx-auto mb-6 inline-flex w-fit items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-2 text-xs font-medium text-primary-soft lg:mx-0">
            <Sparkles className="h-3.5 w-3.5" />
            AI-powered pantry intelligence
          </div>

          <h1 className="text-4xl font-extrabold leading-[1.05] tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            Waste less. Save more.
            <br />
            Use what you already have.
          </h1>

          <p className="mx-auto mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg sm:leading-8 lg:mx-0">
            
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start">
            <Link to="/register">
              <Button
                size="lg"
                className="group min-w-44 bg-gradient-pink text-white shadow-glow hover:opacity-95"
              >
                Get Started
                <ArrowRight className="ml-1.5 h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Button>
            </Link>

            <a href="#features">
              <Button
                size="lg"
                variant="outline"
                className="min-w-44 border-border"
              >
                View Features
              </Button>
            </a>
          </div>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 text-xs text-muted-foreground sm:flex-row sm:gap-6 lg:justify-start">
            <div className="flex items-center gap-1.5">
              <Check className="h-3.5 w-3.5 text-success" />
              Simple pantry management
            </div>

            <div className="flex items-center gap-1.5">
              <Check className="h-3.5 w-3.5 text-success" />
              Actionable waste predictions
            </div>

            <div className="flex items-center gap-1.5">
              <Check className="h-3.5 w-3.5 text-success" />
              Smarter grocery decisions
            </div>
          </div>
        </motion.div>

        {/* Right: NYT-Cooking-style photo card with floating info panel */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.7, delay: 0.15 }}
          className="relative mx-auto w-full max-w-xl lg:mx-0"
        >
          {/* small peeking photo, echoes the second plate in a cooking-mag hero */}
          <div className="absolute -top-6 right-6 z-20 hidden h-28 w-28 overflow-hidden rounded-2xl border-4 border-background shadow-xl sm:block">
            <img
              src="https://images.unsplash.com/photo-1590311824865-bac58a024e51?auto=format&fit=crop&w=400&q=80"
              alt="Clear glass jars of pantry staples"
              className="h-full w-full object-cover"
            />
          </div>

          <div className="relative overflow-hidden rounded-3xl border border-border shadow-glow">
            <img
              src="https://images.unsplash.com/photo-1580116270858-8a0d62b15426?auto=format&fit=crop&w=1200&q=80"
              alt="A well-stocked pantry shelf"
              className="h-[420px] w-full object-cover sm:h-[480px]"
            />

            {/* gradient scrim so the floating card stays legible over the photo */}
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-black/0 to-black/0" />

            {/* top-right utility icons, like a save / share bar on a recipe photo */}
            <div className="absolute right-4 top-4 z-20 flex gap-2">
              <button
                type="button"
                aria-label="Save"
                className="grid h-9 w-9 place-items-center rounded-full bg-background/80 text-foreground backdrop-blur transition-colors hover:text-primary"
              >
                <Bookmark className="h-4 w-4" />
              </button>

              <button
                type="button"
                aria-label="Share"
                className="grid h-9 w-9 place-items-center rounded-full bg-background/80 text-foreground backdrop-blur transition-colors hover:text-primary"
              >
                <Share2 className="h-4 w-4" />
              </button>
            </div>

            {/* floating info card, the "Recipe of the Day" equivalent */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.5 }}
              className="absolute bottom-5 left-5 right-5 z-20 max-w-[280px] rounded-2xl border border-primary/20 bg-card/95 p-5 shadow-xl backdrop-blur-sm sm:right-auto"
            >
              <div className="mb-3 grid h-9 w-9 place-items-center rounded-full bg-gradient-pink text-white shadow-glow">
                <ShieldAlert className="h-4 w-4" />
              </div>

              <div className="text-[10px] font-semibold uppercase tracking-widest text-primary-soft">
                Waste-Risk Pick of the Day
              </div>

              <h3 className="mt-1 text-lg font-bold leading-snug text-foreground">
                Ripe tomatoes, use within 2 days
              </h3>

              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
                Flagged from your pantry based on purchase date and how your
                household typically uses this item.
              </p>

              <div className="mt-3 text-[11px] font-semibold text-primary-soft">
                Predicted by WasteWise AI
              </div>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section
      id="features"
      className="scroll-mt-20 border-t border-border/60 bg-secondary-bg/40"
    >
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
        <SectionHead
          eyebrow="Features"
          title="Everything your kitchen needs"
          desc="Eight focused capabilities that turn pantry management into a simple, intelligent, and waste-conscious household routine."
        />

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, index) => {
            const Icon = feature.icon;

            return (
              <motion.article
                key={feature.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{
                  once: true,
                  margin: "-60px",
                }}
                transition={{
                  duration: 0.4,
                  delay: index * 0.04,
                }}
                whileHover={{
                  y: -5,
                }}
                className="group rounded-2xl border border-border bg-card p-6 transition-colors duration-300 hover:border-primary/40"
              >
                <div className="mb-5 grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary transition-all duration-300 group-hover:scale-105 group-hover:bg-primary/15">
                  <Icon className="h-5 w-5" />
                </div>

                <h3 className="text-base font-semibold text-foreground">
                  {feature.title}
                </h3>

                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {feature.desc}
                </p>
              </motion.article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function About() {
  return (
    <section
      id="about"
      className="scroll-mt-20 border-t border-border/60"
    >
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
        <SectionHead
          eyebrow="About WasteWise"
          title="A smarter way to manage food at home"
          desc="WasteWise AI helps households understand what they own, what should be used next, and where unnecessary food waste can be prevented."
        />

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {aboutItems.map((item, index) => {
            const Icon = item.icon;

            return (
              <motion.article
                key={item.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{
                  once: true,
                  margin: "-60px",
                }}
                transition={{
                  duration: 0.4,
                  delay: index * 0.08,
                }}
                whileHover={{
                  y: -4,
                }}
                className="group rounded-2xl border border-border bg-card p-6 transition-colors duration-300 hover:border-primary/40"
              >
                <div className="mb-5 grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary transition-transform duration-300 group-hover:scale-105">
                  <Icon className="h-5 w-5" />
                </div>

                <h3 className="text-lg font-semibold text-foreground">
                  {item.title}
                </h3>

                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {item.desc}
                </p>
              </motion.article>
            );
          })}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.45 }}
          className="mt-5 rounded-2xl border border-primary/30 bg-primary-dark/30 p-6 sm:p-8"
        >
          <div className="grid items-center gap-8 lg:grid-cols-[1.2fr_0.8fr]">
            <div>
              <div className="text-xs font-semibold uppercase tracking-widest text-primary-soft">
                Why WasteWise
              </div>

              <h3 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                Make decisions before food becomes waste.
              </h3>

              <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
                WasteWise does more than record expired food. It helps users act
                earlier through expiry awareness, pantry visibility,
                consumption information, and waste-risk predictions.
              </p>
            </div>

            <div className="space-y-3">
              {[
                "Know what is already in your pantry",
                "Use high-risk products earlier",
                "Avoid unnecessary duplicate purchases",
                "Build better household habits",
              ].map((item) => (
                <div
                  key={item}
                  className="flex items-center gap-3 rounded-xl border border-border bg-card/70 px-4 py-3"
                >
                  <Check className="h-4 w-4 shrink-0 text-success" />

                  <span className="text-sm text-foreground">
                    {item}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function ContactCTA() {
  return (
    <section
      id="contact"
      className="scroll-mt-20 border-t border-border/60"
    >
      <div className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
        >
          <div className="mx-auto mb-5 inline-flex w-fit items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-primary-soft">
            Get Started
          </div>

          <h2 className="text-3xl font-bold sm:text-4xl">
            Ready to make your pantry{" "}
            <span className="gradient-text-pink">smarter?</span>
          </h2>

          <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
            Create your account in seconds and start tracking groceries,
            preventing waste, and rescuing food today.
          </p>

          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <Link to="/register">
              <Button
                size="lg"
                className="min-w-40 bg-gradient-pink text-white shadow-glow hover:opacity-95"
              >
                Create Account
              </Button>
            </Link>

            <Link to="/login">
              <Button
                size="lg"
                variant="outline"
                className="min-w-40 border-border"
              >
                Login
              </Button>
            </Link>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function SectionHead({
  eyebrow,
  title,
  desc,
  align = "center",
}: {
  eyebrow: string;
  title: string;
  desc: string;
  align?: "left" | "center";
}) {
  return (
    <div className={align === "center" ? "text-center" : ""}>
      <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-primary-soft">
        {eyebrow}
      </div>

      <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
        {title}
      </h2>

      <p
        className={`mt-3 leading-7 text-muted-foreground ${
          align === "center" ? "mx-auto max-w-2xl" : "max-w-2xl"
        }`}
      >
        {desc}
      </p>
    </div>
  );
}
