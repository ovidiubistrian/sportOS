import type { Site } from "@/lib/site";

/**
 * The front page of a club that has not written anything yet.
 *
 * The carousel is the usual opening, and it renders nothing without articles —
 * correctly, since a carousel of no slides is not a thing. But that left a club
 * on its first day with a home page that begins at the newsletter signup, after
 * it had just uploaded a picture and been told it was the home page image.
 *
 * So this stands in: the picture, the club's name over it, and its tagline.
 * It disappears the moment there is a first article, because from then on the
 * club's own news is the better opening and this would be a second hero.
 */
export function OpeningHero({ site }: { site: Site }) {
  const image = site.branding.hero_url;

  return (
    <section
      className="relative isolate flex min-h-[380px] items-end overflow-hidden bg-surface-deep text-surface-deep-ink sm:min-h-[460px] lg:min-h-[540px]"
    >
      {image && (
        <>
          <img
            src={image}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            // The page's largest paint, and there is nothing above it.
            loading="eager"
          />
          {/* Dark at the foot, clear at the head: the club's name has to stay
              legible over a photograph nobody has colour-checked. */}
          <div
            aria-hidden
            className="absolute inset-0"
            style={{
              background:
                "linear-gradient(to top, rgb(0 0 0 / 0.72), rgb(0 0 0 / 0.25) 45%, transparent)",
            }}
          />
        </>
      )}

      <div className="relative mx-auto w-full max-w-6xl px-6 pb-12">
        <h1
          className="font-display text-4xl font-extrabold tracking-tighter uppercase sm:text-6xl lg:text-7xl"
          style={{ color: image ? "#fff" : undefined }}
        >
          {site.name}
        </h1>
        {site.branding.tagline && (
          <p
            className="mt-3 max-w-2xl text-lg"
            style={{ color: image ? "rgb(255 255 255 / 0.85)" : undefined }}
          >
            {site.branding.tagline}
          </p>
        )}
      </div>
    </section>
  );
}
