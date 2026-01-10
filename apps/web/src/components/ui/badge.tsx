import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-badge border px-[15px] text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 h-[25px]",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        ghost: "border-transparent bg-transparent text-muted-foreground hover:text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  selected?: boolean
}

function Badge({ className, variant, selected, ...props }: BadgeProps) {
  // If selected is explicitly provided, it overrides variant
  // selected=true -> default (primary filled)
  // selected=false -> ghost (transparent gray text)
  let finalVariant = variant
  if (selected !== undefined) {
    finalVariant = selected ? "default" : "ghost"
  }
  
  return (
    <div className={cn(badgeVariants({ variant: finalVariant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
