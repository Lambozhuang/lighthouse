// The few icons the app needs, drawn as 24×24 outlines that take the text color.

import type { ReactNode } from 'react'

function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      {children}
    </svg>
  )
}

type IconProps = { size?: number }

export const LogoIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9.5 10h5l1.5 11h-8z" />
    <path d="M10 6.5h4V10h-4z" />
    <path d="M12 3.5v3" />
    <path d="M6.5 6 3 4.5M6.5 8.5H3M17.5 6 21 4.5M17.5 8.5H21" />
  </Icon>
)

export const MenuIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)

export const CloseIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Icon>
)

export const PlusIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)

export const InboxIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m4 13 2.5-7.5h11L20 13v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z" />
    <path d="M4 13h4.5l1 2.5h5l1-2.5H20" />
  </Icon>
)

export const NotesIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M7.5 3.5h6l4 4v12a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1z" />
    <path d="M13.5 3.5v4h4M9.5 12.5h5M9.5 16h5" />
  </Icon>
)

export const TrashIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.5h6.4a1.5 1.5 0 0 0 1.5-1.5l.8-12M10 11v5.5M14 11v5.5" />
  </Icon>
)

export const SendIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Icon>
)

export const StopIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none" />
  </Icon>
)

export const SearchIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-4.5-4.5" />
  </Icon>
)

export const ArrowLeftIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Icon>
)

export const ExternalIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9 6h9v9M18 6 7 17" />
  </Icon>
)

export const SignOutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14 4.5h4a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-4M10 8l-4 4 4 4M6 12h9" />
  </Icon>
)
