// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconFrame({
  children,
  ...props
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function ArrowIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M5 12h14M14 7l5 5-5 5" />
    </IconFrame>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="m5 12 4 4L19 6" />
    </IconFrame>
  );
}

export function CodeIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" />
    </IconFrame>
  );
}

export function ConsoleIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="m7 9 3 3-3 3M13 15h4" />
    </IconFrame>
  );
}

export function BlocksIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <rect x="3" y="4" width="8" height="7" rx="2" />
      <rect x="13" y="4" width="8" height="7" rx="2" />
      <rect x="8" y="13" width="8" height="7" rx="2" />
      <path d="M7 11v2h5M17 11v2h-5" />
    </IconFrame>
  );
}

export function ProtocolIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="18" cy="18" r="3" />
      <path d="m9 11 6-4M9 13l6 4" />
    </IconFrame>
  );
}

export function RadioIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <circle cx="7" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <path d="M11 8a5.5 5.5 0 0 1 0 8M14 5a9.5 9.5 0 0 1 0 14" />
    </IconFrame>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6l-7-3Z" />
      <path d="m9 12 2 2 4-5" />
    </IconFrame>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M5 7h14M5 12h14M5 17h14" />
    </IconFrame>
  );
}

export function MailIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <rect x="3" y="5" width="18" height="14" rx="3" />
      <path d="m5 8 7 5 7-5" />
    </IconFrame>
  );
}

export function ExternalIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M14 5h5v5M19 5l-8 8" />
      <path d="M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
    </IconFrame>
  );
}
