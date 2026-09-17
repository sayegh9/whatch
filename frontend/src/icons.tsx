import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function LibraryIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 5v14M8 4v16M12 6v13M16 4l4 15" />
    </IconBase>
  );
}

export function ReviewIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 5h8l2 3v11H6V8l2-3Z" />
      <path d="M9 5V3h6v2M12 10v4M12 17h.01" />
    </IconBase>
  );
}

export function ImportIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 3v12M8 7l4-4 4 4M5 14v6h14v-6" />
    </IconBase>
  );
}

export function TonightIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M19 15.5A8 8 0 0 1 8.5 5a8 8 0 1 0 10.5 10.5Z" />
      <path d="m16.5 4 .4 1.1L18 5.5l-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4.4-1.1Z" />
    </IconBase>
  );
}

export function WatchLaterIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M6 4h12v16l-6-3.5L6 20V4Z" />
      <path d="M9 9h6M12 6v6" />
    </IconBase>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="11" cy="11" r="6" />
      <path d="m16 16 4 4" />
    </IconBase>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 5v14M5 12h14" />
    </IconBase>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 3v12M8 11l4 4 4-4M5 19h14" />
    </IconBase>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m6 6 12 12M18 6 6 18" />
    </IconBase>
  );
}

export function ExternalIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M14 5h5v5M19 5l-8 8" />
      <path d="M17 13v6H5V7h6" />
    </IconBase>
  );
}

export function LinkIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M10 13a4 4 0 0 0 5.7.1l2.2-2.2a4 4 0 0 0-5.6-5.6l-1.3 1.3" />
      <path d="M14 11a4 4 0 0 0-5.7-.1l-2.2 2.2a4 4 0 0 0 5.6 5.6l1.3-1.3" />
    </IconBase>
  );
}
