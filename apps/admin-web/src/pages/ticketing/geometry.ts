/**
 * Turning "north stand, third sector of four" into a polygon.
 *
 * A club administrator should not draw shapes. They know their ground as
 * *sides* — main stand, north end, away corner — so the form asks for a side
 * and this works out the rectangle. The specification says advanced CAD-style
 * drawing is not required, and this is the practical reading of that: the map
 * is recognisable within a minute of typing, and nobody drags a vertex.
 *
 * The coordinate space is the same abstract 1000x1000 the seed and the
 * buyer-facing map use, with the pitch in the middle. Geometry is stored as
 * JSON on the stand and the sector, so a club that later wants a hand-drawn
 * polygon can have one without a migration — this function only decides the
 * default.
 */

export const SIDES = ["WEST", "EAST", "NORTH", "SOUTH"] as const;
export type Side = (typeof SIDES)[number];

/** The pitch, and the band each side occupies around it. */
const PITCH = { x: 300, y: 250, width: 400, height: 500 };

const BANDS: Record<Side, { x: number; y: number; width: number; height: number }> = {
  WEST: { x: 120, y: PITCH.y, width: 170, height: PITCH.height },
  EAST: { x: 710, y: PITCH.y, width: 170, height: PITCH.height },
  NORTH: { x: PITCH.x, y: 90, width: PITCH.width, height: 150 },
  SOUTH: { x: PITCH.x, y: 760, width: PITCH.width, height: 150 },
};

/** How much of the band a stand leaves as a gap on each edge. */
const INSET = 10;

export interface Polygon {
  points: [number, number][];
}

function rectangle(x: number, y: number, width: number, height: number): Polygon {
  return {
    points: [
      [x, y],
      [x + width, y],
      [x + width, y + height],
      [x, y + height],
    ],
  };
}

/** The whole band for one side of the ground. */
export function standGeometry(side: Side): Polygon {
  const band = BANDS[side];
  return rectangle(band.x, band.y, band.width, band.height);
}

/**
 * One sector's slice of its stand.
 *
 * Sectors divide the stand along its *long* axis — top to bottom on the side
 * stands, left to right behind the goals — which is how a ground is actually
 * split, and what makes the resulting map read correctly without anybody
 * adjusting it.
 */
export function sectionGeometry(side: Side, index: number, count: number): Polygon {
  const band = BANDS[side];
  const total = Math.max(count, 1);
  const position = Math.min(Math.max(index, 0), total - 1);

  const horizontal = side === "NORTH" || side === "SOUTH";
  const gap = 6;

  if (horizontal) {
    const width = (band.width - INSET * 2 - gap * (total - 1)) / total;
    return rectangle(
      band.x + INSET + position * (width + gap),
      band.y + INSET,
      width,
      band.height - INSET * 2,
    );
  }

  const height = (band.height - INSET * 2 - gap * (total - 1)) / total;
  return rectangle(
    band.x + INSET,
    band.y + INSET + position * (height + gap),
    band.width - INSET * 2,
    height,
  );
}

/** Which side a stand was placed on, recovered from what was stored. */
export function sideOf(geometry: { points?: [number, number][] } | undefined): Side {
  const first = geometry?.points?.[0];
  if (!first) return "WEST";
  const [x, y] = first;
  if (y < PITCH.y) return "NORTH";
  if (y >= PITCH.y + PITCH.height) return "SOUTH";
  return x < PITCH.x ? "WEST" : "EAST";
}

/** A code from a name — "Tribuna Principală" becomes "TRIBUNAPRI". */
export function codeFrom(name: string, max = 10): string {
  const cleaned = name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]/g, "")
    .toUpperCase();
  return cleaned.slice(0, max) || "SECT";
}
