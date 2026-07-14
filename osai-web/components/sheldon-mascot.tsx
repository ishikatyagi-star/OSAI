import Image from "next/image";

export type SheldonMascotState =
  | "alerting"
  | "approving"
  | "handoff"
  | "happy"
  | "idle"
  | "ingesting"
  | "launching"
  | "learning"
  | "main"
  | "mapping"
  | "orchestrating"
  | "protecting"
  | "recovering"
  | "searching"
  | "syncing"
  | "thinking";

type Props = {
  state: SheldonMascotState;
  size?: number;
  alt?: string;
  className?: string;
  priority?: boolean;
};

export function SheldonMascot({ state, size = 96, alt = "", className = "", priority = false }: Props) {
  return (
    <Image
      src={`/brand/sheldon-ai-mascot-${state}.png`}
      width={size}
      height={size}
      sizes={`${size}px`}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      className={`sheldon-mascot ${className}`.trim()}
      priority={priority}
    />
  );
}
