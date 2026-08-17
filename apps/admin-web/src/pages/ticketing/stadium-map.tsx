import { cn } from "@footbola/ui";
import { useCallback, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, WheelEvent } from "react";

import type { LayoutSection, LayoutStand, StadiumLayout } from "@footbola/api-client";

/**
 * The stadium, drawn.
 *
 * One component for three jobs — the admin editor, the match overview and the
 * buyer-facing picker — because they are the same drawing with different
 * colours on it. The alternative was three maps that would drift, and a
 * supporter seeing a different ground from the one the club drew.
 *
 * Geometry arrives as polygons in an abstract 1000x1000 space with the pitch in
 * the middle. Nothing here invents shapes: if a club moves a stand, the club's
 * data moves it, not a constant in this file.
 *
 * **Zoom and pan are deliberately plain.** Wheel to zoom about the cursor, drag
 * to pan, a button to reset. No inertia, no animation on the transform — an
 * administrator assigning seats to a price zone wants the map to stop where
 * they put it, and momentum scrolling on a precise task is an irritation rather
 * than a delight.
 *
 * Keyboard access is real, not decorative: every sector is a focusable element
 * with a label, so the map is usable without a mouse and legible to a screen
 * reader as a list of sectors with capacities.
 */

const VIEW = 1000;
const MIN_SCALE = 0.6;
const MAX_SCALE = 6;

/** The pitch, in the same coordinate space the seeded geometry uses. */
const PITCH = { x: 300, y: 250, width: 400, height: 500 };

export type SectionTone = "zone" | "availability" | "neutral";

export interface SectionStatus {
  /** 0–1. Drives the availability shading. */
  ratio?: number;
  label?: string;
  disabled?: boolean;
}

/**
 * Every string the map draws. Passed in rather than looked up here: this
 * component is shared with the buyer-facing picker, which resolves its
 * messages from a different catalogue.
 */
export interface StadiumMapLabels {
  zoomIn: string;
  zoomOut: string;
  reset: string;
  seats: string;
  gate: string;
  available: string;
  filling: string;
  almostGone: string;
  unavailable: string;
}

const FALLBACK_LABELS: StadiumMapLabels = {
  zoomIn: "Zoom in",
  zoomOut: "Zoom out",
  reset: "Reset",
  seats: "seats",
  gate: "Gate",
  available: "Available",
  filling: "Filling up",
  almostGone: "Almost gone",
  unavailable: "Unavailable",
};

export interface StadiumMapProps {
  layout: StadiumLayout;
  labels?: Partial<StadiumMapLabels>;
  /** How sectors are coloured: by price zone, by how full they are, or flat. */
  tone?: SectionTone;
  selectedSectionIds?: string[];
  statuses?: Record<string, SectionStatus>;
  onSelectSection?: (section: LayoutSection, stand: LayoutStand) => void;
  className?: string;
  /** Hides the legend when the surrounding screen already carries one. */
  showLegend?: boolean;
}

function centroid(points: [number, number][]): [number, number] {
  if (!points.length) return [VIEW / 2, VIEW / 2];
  const sum = points.reduce<[number, number]>(
    (acc, [x, y]) => [acc[0] + x, acc[1] + y],
    [0, 0],
  );
  return [sum[0] / points.length, sum[1] / points.length];
}

function toPath(points: [number, number][] | undefined): string {
  if (!points?.length) return "";
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

/**
 * Green through amber to red as a sector fills.
 *
 * Not a gradient over a continuous scale: three bands, because the question an
 * administrator actually asks is "is this sector fine, filling or gone", and a
 * subtle shift between 61% and 64% answers nothing.
 */
function availabilityFill(ratio: number | undefined): string {
  if (ratio === undefined) return "var(--color-surface-2, #f1f5f9)";
  if (ratio > 0.5) return "#10b98122";
  if (ratio > 0.15) return "#f59e0b33";
  if (ratio > 0) return "#ef444433";
  return "#94a3b833";
}

function availabilityStroke(ratio: number | undefined): string {
  if (ratio === undefined) return "#cbd5e1";
  if (ratio > 0.5) return "#10b981";
  if (ratio > 0.15) return "#f59e0b";
  if (ratio > 0) return "#ef4444";
  return "#94a3b8";
}

export function StadiumMap({
  layout,
  labels: given,
  tone = "zone",
  selectedSectionIds = [],
  statuses = {},
  onSelectSection,
  className,
  showLegend = true,
}: StadiumMapProps) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragging = useRef<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const selected = useMemo(() => new Set(selectedSectionIds), [selectedSectionIds]);
  const labels = useMemo(() => ({ ...FALLBACK_LABELS, ...given }), [given]);

  const onWheel = useCallback((event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setScale((current) => {
      const next = current * (event.deltaY < 0 ? 1.12 : 1 / 1.12);
      return Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    });
  }, []);

  const onPointerDown = useCallback((event: PointerEvent<SVGSVGElement>) => {
    // Only a background drag pans; a drag that starts on a sector is a click
    // the user is still making up their mind about.
    if ((event.target as Element).closest("[data-section]")) return;
    dragging.current = { x: event.clientX - offset.x, y: event.clientY - offset.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [offset]);

  const onPointerMove = useCallback((event: PointerEvent<SVGSVGElement>) => {
    if (!dragging.current) return;
    setOffset({
      x: event.clientX - dragging.current.x,
      y: event.clientY - dragging.current.y,
    });
  }, []);

  const onPointerUp = useCallback((event: PointerEvent<SVGSVGElement>) => {
    dragging.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const reset = useCallback(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  const activate = (section: LayoutSection, stand: LayoutStand) => {
    if (statuses[section.id]?.disabled) return;
    onSelectSection?.(section, stand);
  };

  const onSectionKeyDown = (
    event: KeyboardEvent<SVGGElement>,
    section: LayoutSection,
    stand: LayoutStand,
  ) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(section, stand);
    }
  };

  return (
    <div className={cn("relative", className)}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW} ${VIEW}`}
        className="w-full touch-none select-none rounded-xl bg-surface-2"
        role="group"
        aria-label={`${layout.venue.name} — ${layout.configuration.name}`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <g
          transform={`translate(${offset.x} ${offset.y}) scale(${scale}) translate(${
            (VIEW * (1 - scale)) / (2 * scale)
          } ${(VIEW * (1 - scale)) / (2 * scale)})`}
        >
          {/* The pitch. Drawn first so everything else sits above it. */}
          <rect
            x={PITCH.x}
            y={PITCH.y}
            width={PITCH.width}
            height={PITCH.height}
            rx={6}
            className="fill-emerald-600/15 stroke-emerald-700/40"
            strokeWidth={2}
          />
          <line
            x1={PITCH.x}
            y1={PITCH.y + PITCH.height / 2}
            x2={PITCH.x + PITCH.width}
            y2={PITCH.y + PITCH.height / 2}
            className="stroke-emerald-700/40"
            strokeWidth={2}
          />
          <circle
            cx={PITCH.x + PITCH.width / 2}
            cy={PITCH.y + PITCH.height / 2}
            r={52}
            className="fill-none stroke-emerald-700/40"
            strokeWidth={2}
          />

          {layout.stands.map((stand) => (
            <g key={stand.id}>
              <polygon
                points={toPath(stand.geometry?.points)}
                className="fill-surface stroke-border"
                strokeWidth={1.5}
                rx={4}
              />
              {stand.sections.map((section) => {
                const status = statuses[section.id];
                const isSelected = selected.has(section.id);
                const points = section.geometry?.points ?? [];
                const [cx, cy] = centroid(points);

                const fill =
                  tone === "availability"
                    ? availabilityFill(status?.ratio)
                    : tone === "zone" && section.price_zone
                      ? `${section.price_zone.colour}33`
                      : "var(--color-surface, #ffffff)";
                const stroke =
                  tone === "availability"
                    ? availabilityStroke(status?.ratio)
                    : (section.price_zone?.colour ?? "#94a3b8");

                return (
                  <g
                    key={section.id}
                    data-section={section.id}
                    role="button"
                    tabIndex={status?.disabled ? -1 : 0}
                    aria-label={`${stand.name}, ${section.name}, ${
                      status?.label ?? `${section.capacity} ${labels.seats}`
                    }`}
                    aria-pressed={isSelected}
                    className={cn(
                      "outline-none transition-opacity",
                      status?.disabled
                        ? "cursor-not-allowed opacity-40"
                        : onSelectSection
                          ? "cursor-pointer hover:opacity-85"
                          : "",
                    )}
                    onClick={() => activate(section, stand)}
                    onKeyDown={(event) => onSectionKeyDown(event, section, stand)}
                  >
                    <polygon
                      points={toPath(points)}
                      fill={fill}
                      stroke={isSelected ? "#0f172a" : stroke}
                      strokeWidth={isSelected ? 4 : 2}
                    />
                    <text
                      x={cx}
                      y={cy - 6}
                      textAnchor="middle"
                      className="pointer-events-none fill-text text-[15px] font-medium"
                    >
                      {section.code}
                    </text>
                    <text
                      x={cx}
                      y={cy + 14}
                      textAnchor="middle"
                      className="pointer-events-none fill-text-secondary text-[13px]"
                      data-numeric
                    >
                      {status?.label ?? section.capacity}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}

          {/* Gates, drawn on the outside edge nearest their sectors. */}
          {layout.gates.map((gate, index) => {
            const angle = (index / Math.max(layout.gates.length, 1)) * Math.PI * 2 - Math.PI / 2;
            const gx = VIEW / 2 + Math.cos(angle) * 455;
            const gy = VIEW / 2 + Math.sin(angle) * 455;
            return (
              <g key={gate.id} aria-label={`${labels.gate} ${gate.code}`}>
                <circle cx={gx} cy={gy} r={20} className="fill-navy stroke-white" strokeWidth={2} />
                <text
                  x={gx}
                  y={gy + 6}
                  textAnchor="middle"
                  className="pointer-events-none fill-white text-[16px] font-semibold"
                >
                  {gate.code}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="absolute right-3 top-3 flex gap-1.5">
        <button
          type="button"
          onClick={() => setScale((s) => Math.min(MAX_SCALE, s * 1.25))}
          className="size-8 rounded-lg border border-border bg-surface text-sm font-medium shadow-sm hover:bg-surface-2"
          aria-label={labels.zoomIn}
        >
          +
        </button>
        <button
          type="button"
          onClick={() => setScale((s) => Math.max(MIN_SCALE, s / 1.25))}
          className="size-8 rounded-lg border border-border bg-surface text-sm font-medium shadow-sm hover:bg-surface-2"
          aria-label={labels.zoomOut}
        >
          −
        </button>
        <button
          type="button"
          onClick={reset}
          className="h-8 rounded-lg border border-border bg-surface px-2.5 text-xs font-medium shadow-sm hover:bg-surface-2"
        >
          {labels.reset}
        </button>
      </div>

      {showLegend && tone === "zone" && layout.price_zones.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
          {layout.price_zones.map((zone) => (
            <li key={zone.id} className="flex items-center gap-2 text-xs text-text-secondary">
              <span
                className="size-3 rounded-sm border"
                style={{ backgroundColor: `${zone.colour}33`, borderColor: zone.colour }}
                aria-hidden
              />
              {zone.name}
            </li>
          ))}
        </ul>
      )}

      {showLegend && tone === "availability" && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-text-secondary">
          {[
            { colour: "#10b981", label: labels.available },
            { colour: "#f59e0b", label: labels.filling },
            { colour: "#ef4444", label: labels.almostGone },
            { colour: "#94a3b8", label: labels.unavailable },
          ].map((entry) => (
            <li key={entry.label} className="flex items-center gap-2">
              <span
                className="size-3 rounded-sm border"
                style={{ backgroundColor: `${entry.colour}33`, borderColor: entry.colour }}
                aria-hidden
              />
              {entry.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
