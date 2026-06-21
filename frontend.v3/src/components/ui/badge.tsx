import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive text-destructive-foreground",
        outline: "text-foreground",
        live: "border-transparent bg-[hsl(var(--live))]/15 text-[hsl(var(--live))]",
        typical: "border-transparent bg-[hsl(var(--typical))]/15 text-[hsl(var(--typical))]",
        modeled: "border-transparent bg-[hsl(var(--modeled))]/15 text-[hsl(var(--modeled))]",
        warning: "border-transparent bg-[hsl(var(--warning))]/15 text-[hsl(var(--warning))]",
        success: "border-transparent bg-[hsl(var(--success))]/15 text-[hsl(var(--success))]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
