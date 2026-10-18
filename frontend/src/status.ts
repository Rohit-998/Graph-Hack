import type { Status } from './api'

// Status is never colour-only: each state also has an icon and a text label.
export const STATUS_ICON: Record<Status, string> = { healthy: '●', degraded: '▲', down: '✕' }
