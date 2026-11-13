/** Fill opacity of the edge tab after 3 s without interaction. Only the fill fades. */
export const EDGE_IDLE_OPACITY = 0.35;
/**
 * Opaque outline that never fades: the light-theme primary (#2A767C) measures
 * 5.28:1 on white and 3.98:1 on black, so the tab stays >= 3:1 (WCAG 1.4.11)
 * on any app page in either theme.
 */
export const EDGE_OUTLINE = "#2A767C";
