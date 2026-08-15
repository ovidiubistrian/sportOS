import type { Branding } from "@footbola/api-client";

/**
 * Template preview.
 *
 * A scale model of the four public layouts, drawn from the same palette the API
 * derives — so what a club sees here is the contrast maths the live site will
 * actually apply, not an approximation. It shows *layout character* rather than
 * pixel-exact output: enough to choose between four templates, and cheap enough
 * to update on every keystroke of a colour picker.
 */

function palette(branding: Branding) {
  return {
    brand: branding.palette["--brand"] ?? branding.color_primary,
    onBrand: branding.palette["--brand-contrast"] ?? "#FFFFFF",
    brandText: branding.palette["--brand-text"] ?? branding.color_primary,
    secondary: branding.palette["--brand-secondary"] ?? null,
  };
}

function Bar({ width, tone = "#D8DDE4" }: { width: string; tone?: string }) {
  return <div className="h-1.5 rounded-full" style={{ width, background: tone }} />;
}

function ClassicPreview({ branding, clubName, shortName }: PreviewProps) {
  const c = palette(branding);
  return (
    <div className="bg-white">
      <div className="h-1" style={{ background: c.brand }} />
      <div className="flex flex-col items-center gap-1.5 border-b border-[#E4E7EB] py-4">
        <div
          className="grid size-7 place-items-center rounded-sm text-[8px] font-bold"
          style={{ background: c.brand, color: c.onBrand }}
        >
          {shortName.slice(0, 3)}
        </div>
        <p className="text-[11px] font-bold text-[#12161C]">{clubName}</p>
        <div className="flex gap-3 pt-1">
          {["Home", "Teams", "Club"].map((item) => (
            <span key={item} className="text-[7px] tracking-wider text-[#5B6672] uppercase">
              {item}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-2 p-4">
        <div className="h-1.5 w-16 rounded-full" style={{ background: c.brand }} />
        <div className="space-y-1 rounded border border-[#E4E7EB] p-2">
          <Bar width="70%" />
          <Bar width="50%" />
          <Bar width="60%" />
        </div>
      </div>
    </div>
  );
}

function BoldPreview({ branding, clubName, shortName }: PreviewProps) {
  const c = palette(branding);
  return (
    <div className="bg-white">
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{ background: c.brand, color: c.onBrand }}
      >
        <span className="text-[9px] font-extrabold tracking-tight uppercase">
          {shortName}
        </span>
        <div className="flex gap-2 opacity-80">
          {["Home", "Teams"].map((item) => (
            <span key={item} className="text-[6px] font-bold tracking-widest uppercase">
              {item}
            </span>
          ))}
        </div>
      </div>
      <div className="px-4 py-6" style={{ background: c.brand, color: c.onBrand }}>
        <p className="text-[20px] leading-none font-extrabold tracking-tighter uppercase">
          {clubName}
        </p>
        <div
          className="mt-3 inline-block rounded-sm px-2.5 py-1 text-[6px] font-bold tracking-widest uppercase"
          style={{ background: c.onBrand, color: c.brand }}
        >
          Our teams
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 p-4">
        {[0, 1].map((index) => (
          <div key={index} className="space-y-1.5 rounded border border-[#E4E7EB] p-2">
            <Bar width="80%" tone="#12161C" />
            <Bar width="40%" />
          </div>
        ))}
      </div>
    </div>
  );
}

function CompactPreview({ branding, clubName, shortName }: PreviewProps) {
  const c = palette(branding);
  return (
    <div className="flex gap-3 bg-white p-4">
      <div className="w-14 shrink-0 space-y-2">
        <div
          className="grid size-5 place-items-center rounded-sm text-[6px] font-bold"
          style={{ background: c.brand, color: c.onBrand }}
        >
          {shortName.slice(0, 2)}
        </div>
        <div className="space-y-1">
          {["Home", "Teams", "Club"].map((item, index) => (
            <div
              key={item}
              className="border-l-2 pl-1.5 text-[6px] text-[#5B6672]"
              style={{ borderColor: index === 0 ? c.brand : "transparent" }}
            >
              {item}
            </div>
          ))}
        </div>
      </div>
      <div className="flex-1 space-y-2">
        <p className="text-[10px] font-semibold text-[#12161C]">{clubName}</p>
        <div className="space-y-1 border-y border-[#E4E7EB] py-1.5">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="flex items-center justify-between">
              <Bar width="45%" />
              <Bar width="12%" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function EditorialPreview({ branding, clubName, shortName }: PreviewProps) {
  const c = palette(branding);
  return (
    <div className="bg-white">
      <div className="flex items-center justify-between border-b border-[#E4E7EB] px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <div
            className="grid size-4 place-items-center rounded-sm text-[5px] font-bold"
            style={{ background: c.brand, color: c.onBrand }}
          >
            {shortName.slice(0, 2)}
          </div>
          <span className="text-[9px] font-semibold text-[#12161C]">{clubName}</span>
        </div>
        <div className="flex gap-2">
          {["Home", "Teams", "Club"].map((item) => (
            <span key={item} className="text-[6px] text-[#5B6672]">
              {item}
            </span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-[2fr_1fr] gap-3 p-4">
        <div className="space-y-1.5">
          <span className="text-[6px] tracking-widest uppercase" style={{ color: c.brandText }}>
            Since 1921
          </span>
          <Bar width="95%" tone="#12161C" />
          <Bar width="75%" tone="#12161C" />
          <div className="pt-1 space-y-1">
            <Bar width="100%" />
            <Bar width="85%" />
          </div>
        </div>
        <div className="space-y-1.5 border-l border-[#E4E7EB] pl-3">
          <Bar width="70%" />
          <Bar width="55%" />
        </div>
      </div>
      <div className="flex items-center gap-2 px-4 pb-4">
        <span className="text-[14px] font-semibold" style={{ color: c.brand }}>
          01
        </span>
        <Bar width="50%" tone="#12161C" />
      </div>
    </div>
  );
}

interface PreviewProps {
  branding: Branding;
  clubName: string;
  shortName: string;
}

const PREVIEWS = {
  CLASSIC: ClassicPreview,
  BOLD: BoldPreview,
  COMPACT: CompactPreview,
  EDITORIAL: EditorialPreview,
} as const;

/**
 * A single template thumbnail, unframed.
 *
 * Exported on its own so the template picker can show all four side by side in
 * the club's own colours — choosing a layout from four names and four sentences
 * is guesswork; choosing from four pictures is a decision.
 */
export function TemplateThumbnail(props: PreviewProps) {
  const Preview = PREVIEWS[props.branding.template] ?? ClassicPreview;
  return <Preview {...props} />;
}

export { palette as resolvedPalette };
export type { PreviewProps };
