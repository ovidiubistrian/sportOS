import {
  ApiError,
  useCreateConfiguration,
  useCreateGate,
  useCreatePriceZone,
  useCreateSection,
  useCreateStand,
  useCreateVenue,
  useDeleteGate,
  useDeleteSection,
  useDeleteStand,
  useGenerateSeats,
  type LayoutSection,
  type StadiumLayout,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Dialog,
  Field,
  Input,
  Select,
  Switch,
  useToast,
} from "@footbola/ui";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";
import { codeFrom, sectionGeometry, SIDES, sideOf, standGeometry, type Side } from "./geometry";

/**
 * The editing half of the stadium screen.
 *
 * Everything here writes to a **draft**. The panel is not rendered at all for a
 * published configuration, because the API would refuse every call and a form
 * that submits into a guaranteed error is worse than no form.
 *
 * The shape of the work follows the ground rather than the schema: price zones
 * first (a sector needs one to be priced), then stands, then the sectors inside
 * them, then seats, then the gates that serve them. That is the order a club
 * secretary describes their own stadium in, and it is the order in which each
 * step has everything the next one needs.
 *
 * Geometry is chosen, not drawn — see `geometry.ts`. A club knows its ground as
 * sides, so the form asks for a side and the polygon follows.
 */

interface Props {
  clubId: string;
  venueId?: string;
  configurationId?: string;
  layout?: StadiumLayout;
  /** False for a published configuration: the panel hides itself entirely. */
  editable: boolean;
  onVenueCreated: (venueId: string) => void;
  onConfigurationCreated: (configurationId: string) => void;
}

const ORIENTATIONS = [
  "NORTH_SOUTH",
  "NORTHEAST_SOUTHWEST",
  "EAST_WEST",
  "NORTHWEST_SOUTHEAST",
] as const;

export function StadiumBuilder({
  clubId,
  venueId,
  configurationId,
  layout,
  editable,
  onVenueCreated,
  onConfigurationCreated,
}: Props) {
  const { t } = useI18n();
  const toast = useToast();

  const createVenue = useCreateVenue();
  const createConfiguration = useCreateConfiguration();
  const createZone = useCreatePriceZone();
  const createStand = useCreateStand();
  const createSection = useCreateSection();
  const createGate = useCreateGate();
  const deleteStand = useDeleteStand();
  const deleteSection = useDeleteSection();
  const deleteGate = useDeleteGate();
  const generateSeats = useGenerateSeats();

  const [dialog, setDialog] = useState<
    null | "venue" | "configuration" | "zone" | "stand" | "section" | "gate" | "seats"
  >(null);
  const [target, setTarget] = useState<{ standId?: string; section?: LayoutSection }>({});

  const fail = (error: unknown) => {
    if (error instanceof ApiError) toast.error(error.message);
  };

  // --- venue ---------------------------------------------------------------

  if (!venueId) {
    return (
      <>
        <Card className="p-5">
          <p className="text-sm font-medium text-text">{t("ticketing", "addVenue")}</p>
          <p className="mt-1 text-xs text-text-secondary">{t("ticketing", "addVenueHint")}</p>
          <Button variant="primary" className="mt-4" onClick={() => setDialog("venue")}>
            <Plus className="size-4" />
            {t("ticketing", "addVenue")}
          </Button>
        </Card>
        <VenueDialog
          open={dialog === "venue"}
          onOpenChange={(open) => setDialog(open ? "venue" : null)}
          busy={createVenue.isPending}
          onSubmit={async (body) => {
            try {
              const venue = await createVenue.mutateAsync({ ...body, club_id: clubId });
              onVenueCreated(venue.id);
              setDialog(null);
            } catch (error) {
              fail(error);
            }
          }}
        />
      </>
    );
  }

  if (!configurationId) {
    return (
      <>
        <Card className="p-5">
          <p className="text-sm font-medium text-text">{t("ticketing", "addConfiguration")}</p>
          <p className="mt-1 text-xs text-text-secondary">
            {t("ticketing", "addConfigurationHint")}
          </p>
          <Button variant="primary" className="mt-4" onClick={() => setDialog("configuration")}>
            <Plus className="size-4" />
            {t("ticketing", "addConfiguration")}
          </Button>
        </Card>
        <NameDialog
          open={dialog === "configuration"}
          title={t("ticketing", "addConfiguration")}
          label={t("ticketing", "configurationName")}
          placeholder="Fotbal — standard"
          busy={createConfiguration.isPending}
          onOpenChange={(open) => setDialog(open ? "configuration" : null)}
          onSubmit={async (name) => {
            try {
              const config = await createConfiguration.mutateAsync({
                venueId,
                body: { name },
              });
              onConfigurationCreated(config.id);
              setDialog(null);
            } catch (error) {
              fail(error);
            }
          }}
        />
      </>
    );
  }

  if (!editable) return null;

  const stands = layout?.stands ?? [];
  const zones = layout?.price_zones ?? [];
  const allSections = stands.flatMap((stand) => stand.sections);

  return (
    <div className="space-y-4">
      {/* Price zones first: a sector needs one before it can be priced. */}
      <Card className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-text">{t("ticketing", "priceZones")}</p>
          <Button size="sm" variant="secondary" onClick={() => setDialog("zone")}>
            <Plus className="size-4" />
          </Button>
        </div>
        {zones.length === 0 ? (
          <p className="mt-2 text-xs text-text-tertiary">{t("ticketing", "noPriceZones")}</p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {zones.map((zone) => (
              <li key={zone.id}>
                <Badge tone="outline">
                  <span
                    className="mr-1.5 inline-block size-2.5 rounded-sm"
                    style={{ backgroundColor: zone.colour }}
                    aria-hidden
                  />
                  {zone.name}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-text">{t("ticketing", "stands")}</p>
          <Button size="sm" variant="secondary" onClick={() => setDialog("stand")}>
            <Plus className="size-4" />
          </Button>
        </div>

        {stands.length === 0 ? (
          <p className="mt-2 text-xs text-text-tertiary">{t("ticketing", "noStands")}</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {stands.map((stand) => (
              <li key={stand.id} className="rounded-lg border border-border p-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text">{stand.name}</span>
                  <Badge tone="outline" size="sm">
                    {stand.code}
                  </Badge>
                  <button
                    type="button"
                    className="ml-auto text-text-tertiary hover:text-danger"
                    aria-label={`${t("common", "delete")} ${stand.name}`}
                    onClick={() => void deleteStand.mutateAsync(stand.id).catch(fail)}
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>

                <ul className="mt-2 space-y-1.5">
                  {stand.sections.map((section) => (
                    <li key={section.id} className="flex items-center gap-2 text-sm">
                      <span className="text-text-secondary">{section.name}</span>
                      <span className="text-xs text-text-tertiary" data-numeric>
                        {section.capacity}
                      </span>
                      {section.kind === "RESERVED" && (
                        <button
                          type="button"
                          className="text-xs text-accent hover:underline"
                          onClick={() => {
                            setTarget({ section });
                            setDialog("seats");
                          }}
                        >
                          {t("ticketing", "generateSeats")}
                        </button>
                      )}
                      <button
                        type="button"
                        className="ml-auto text-text-tertiary hover:text-danger"
                        aria-label={`${t("common", "delete")} ${section.name}`}
                        onClick={() => void deleteSection.mutateAsync(section.id).catch(fail)}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>

                <Button
                  size="sm"
                  variant="ghost"
                  className="mt-2"
                  onClick={() => {
                    setTarget({ standId: stand.id });
                    setDialog("section");
                  }}
                >
                  <Plus className="size-3.5" />
                  {t("ticketing", "addSector")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-text">{t("ticketing", "gates")}</p>
          <Button
            size="sm"
            variant="secondary"
            disabled={allSections.length === 0}
            onClick={() => setDialog("gate")}
          >
            <Plus className="size-4" />
          </Button>
        </div>
        {(layout?.gates.length ?? 0) === 0 ? (
          <p className="mt-2 text-xs text-text-tertiary">{t("ticketing", "noGates")}</p>
        ) : (
          <ul className="mt-3 space-y-1.5">
            {layout?.gates.map((gate) => (
              <li key={gate.id} className="flex items-center gap-2 text-sm">
                <Badge tone="outline" size="sm">
                  {gate.code}
                </Badge>
                <span className="truncate text-text-secondary">{gate.name}</span>
                <span className="text-xs text-text-tertiary" data-numeric>
                  {gate.section_ids.length}
                </span>
                <button
                  type="button"
                  className="ml-auto text-text-tertiary hover:text-danger"
                  aria-label={`${t("common", "delete")} ${gate.name}`}
                  onClick={() => void deleteGate.mutateAsync(gate.id).catch(fail)}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <ZoneDialog
        open={dialog === "zone"}
        busy={createZone.isPending}
        onOpenChange={(open) => setDialog(open ? "zone" : null)}
        onSubmit={async (body) => {
          try {
            await createZone.mutateAsync({ configurationId, body });
            setDialog(null);
          } catch (error) {
            fail(error);
          }
        }}
      />

      <StandDialog
        open={dialog === "stand"}
        busy={createStand.isPending}
        onOpenChange={(open) => setDialog(open ? "stand" : null)}
        onSubmit={async ({ name, side }) => {
          try {
            await createStand.mutateAsync({
              configurationId,
              body: {
                name,
                code: codeFrom(name, 8),
                display_order: stands.length,
                geometry: standGeometry(side),
              },
            });
            setDialog(null);
          } catch (error) {
            fail(error);
          }
        }}
      />

      <SectionDialog
        open={dialog === "section"}
        busy={createSection.isPending}
        zones={zones}
        onOpenChange={(open) => setDialog(open ? "section" : null)}
        onSubmit={async (body) => {
          const stand = stands.find((s) => s.id === target.standId);
          if (!stand) return;
          try {
            await createSection.mutateAsync({
              standId: stand.id,
              body: {
                ...body,
                code: codeFrom(`${stand.code}${body.name}`, 12),
                display_order: stand.sections.length,
                // Laid out as one more slice of its stand, so the map redraws
                // sensibly as sectors are added.
                geometry: sectionGeometry(
                  sideOf(stand.geometry),
                  stand.sections.length,
                  stand.sections.length + 1,
                ),
              },
            });
            setDialog(null);
          } catch (error) {
            fail(error);
          }
        }}
      />

      <GateDialog
        open={dialog === "gate"}
        busy={createGate.isPending}
        sections={allSections}
        onOpenChange={(open) => setDialog(open ? "gate" : null)}
        onSubmit={async (body) => {
          try {
            await createGate.mutateAsync({ configurationId, body });
            setDialog(null);
          } catch (error) {
            fail(error);
          }
        }}
      />

      <SeatsDialog
        open={dialog === "seats"}
        busy={generateSeats.isPending}
        section={target.section}
        onOpenChange={(open) => setDialog(open ? "seats" : null)}
        onSubmit={async (plan) => {
          if (!target.section) return;
          try {
            const result = await generateSeats.mutateAsync({
              sectionId: target.section.id,
              plan,
            });
            toast.success(`${result.seats} ${t("ticketing", "seats")}`);
            setDialog(null);
          } catch (error) {
            fail(error);
          }
        }}
      />
    </div>
  );
}

// --- dialogs ----------------------------------------------------------------

function VenueDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [city, setCity] = useState("");
  const [address, setAddress] = useState("");
  const [capacity, setCapacity] = useState("0");
  const [orientation, setOrientation] = useState<string>("NORTH_SOUTH");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "addVenue")}
      description={t("ticketing", "addVenueHint")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={() =>
              onSubmit({
                name: name.trim(),
                code: (code.trim() || codeFrom(name, 8)).toUpperCase(),
                city: city.trim() || null,
                address: address.trim() || null,
                expected_capacity: Number(capacity) || 0,
                pitch_orientation: orientation,
              })
            }
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("ticketing", "venueName")}>
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          )}
        </Field>
        <Field label={t("ticketing", "venueCode")} help={t("ticketing", "venueCodeHint")}>
          {(props) => (
            <Input {...props} value={code} onChange={(e) => setCode(e.target.value)} />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ticketing", "city")}>
            {(props) => (
              <Input {...props} value={city} onChange={(e) => setCity(e.target.value)} />
            )}
          </Field>
          <Field label={t("ticketing", "expectedCapacity")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0}
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label={t("ticketing", "address")}>
          {(props) => (
            <Input {...props} value={address} onChange={(e) => setAddress(e.target.value)} />
          )}
        </Field>
        <Field label={t("ticketing", "pitchOrientation")}>
          {() => (
            <Select
              value={orientation}
              onChange={setOrientation}
              options={ORIENTATIONS.map((value) => ({ value, label: value.replace("_", "–") }))}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}

function NameDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
  title,
  label,
  placeholder,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string) => void;
  busy: boolean;
  title: string;
  label: string;
  placeholder?: string;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={() => onSubmit(name.trim())}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <Field label={label}>
        {(props) => (
          <Input
            {...props}
            value={name}
            placeholder={placeholder}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        )}
      </Field>
    </Dialog>
  );
}

function ZoneDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [colour, setColour] = useState("#1d4ed8");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "addPriceZone")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={() =>
              onSubmit({ name: name.trim(), code: codeFrom(name, 8), colour })
            }
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("ticketing", "zoneName")}>
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          )}
        </Field>
        {/* Colour is data, not styling: the club decides VIP is gold, and the
            buyer-facing map has to agree with the admin one. */}
        <Field label={t("ticketing", "zoneColour")}>
          {(props) => (
            <input
              {...props}
              type="color"
              value={colour}
              onChange={(e) => setColour(e.target.value)}
              className="h-10 w-20 cursor-pointer rounded-lg border border-border bg-surface"
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}

function StandDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: { name: string; side: Side }) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [side, setSide] = useState<Side>("WEST");

  const sideLabel: Record<Side, string> = {
    WEST: t("ticketing", "sideWest"),
    EAST: t("ticketing", "sideEast"),
    NORTH: t("ticketing", "sideNorth"),
    SOUTH: t("ticketing", "sideSouth"),
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "addStand")}
      description={t("ticketing", "addStandHint")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={() => onSubmit({ name: name.trim(), side })}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("ticketing", "standName")}>
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          )}
        </Field>
        <Field label={t("ticketing", "side")} help={t("ticketing", "sideHint")}>
          {() => (
            <Select
              value={side}
              onChange={(value) => setSide(value as Side)}
              options={SIDES.map((value) => ({ value, label: sideLabel[value] }))}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}

function SectionDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
  zones,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: { name: string } & Record<string, unknown>) => void;
  busy: boolean;
  zones: { id: string; name: string }[];
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [reserved, setReserved] = useState(true);
  const [capacity, setCapacity] = useState("0");
  const [zoneId, setZoneId] = useState<string>("");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "addSector")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={() =>
              onSubmit({
                name: name.trim(),
                kind: reserved ? "RESERVED" : "GENERAL_ADMISSION",
                declared_capacity: reserved ? 0 : Number(capacity) || 0,
                price_zone_id: zoneId || null,
              })
            }
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("ticketing", "sectorName")}>
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          )}
        </Field>

        <div className="space-y-1">
          <Switch
            checked={reserved}
            onChange={setReserved}
            label={t("ticketing", "reservedSeating")}
          />
          <p className="text-xs text-text-secondary">
            {t("ticketing", "reservedSeatingHint")}
          </p>
        </div>

        {/* Capacity is the truth for a terrace; for numbered seating the seats
            are, so the field would only be a number to contradict later. */}
        {!reserved && (
          <Field label={t("ticketing", "capacity")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0}
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
              />
            )}
          </Field>
        )}

        <Field label={t("ticketing", "priceZone")}>
          {() => (
            <Select
              value={zoneId}
              onChange={setZoneId}
              options={[
                { value: "", label: "—" },
                ...zones.map((zone) => ({ value: zone.id, label: zone.name })),
              ]}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}

function GateDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
  sections,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: Record<string, unknown>) => void;
  busy: boolean;
  sections: LayoutSection[];
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [kind, setKind] = useState("PUBLIC");
  const [side, setSide] = useState("ANY");
  const [accessible, setAccessible] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);

  const toggle = (id: string) =>
    setChosen((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "addGate")}
      description={t("ticketing", "addGateHint")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim() || !code.trim()}
            onClick={() =>
              onSubmit({
                name: name.trim(),
                code: code.trim().toUpperCase(),
                kind,
                supporter_side: side,
                is_accessible: accessible,
                section_ids: chosen,
              })
            }
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_100px]">
          <Field label={t("ticketing", "gateName")}>
            {(props) => (
              <Input
                {...props}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            )}
          </Field>
          <Field label={t("ticketing", "gateCode")}>
            {(props) => (
              <Input {...props} value={code} onChange={(e) => setCode(e.target.value)} />
            )}
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ticketing", "gateKind")}>
            {() => (
              <Select
                value={kind}
                onChange={setKind}
                options={["PUBLIC", "VIP", "MEDIA", "STAFF", "ACCESSIBLE", "AWAY"].map(
                  (value) => ({ value, label: value }),
                )}
              />
            )}
          </Field>
          <Field label={t("ticketing", "supporterSide")}>
            {() => (
              <Select
                value={side}
                onChange={setSide}
                options={[
                  { value: "ANY", label: t("ticketing", "sideAny") },
                  { value: "HOME", label: t("ticketing", "sideHome") },
                  { value: "AWAY", label: t("ticketing", "sideAway") },
                ]}
              />
            )}
          </Field>
        </div>

        <Switch
          checked={accessible}
          onChange={setAccessible}
          label={t("ticketing", "accessibleEntrance")}
        />

        <fieldset>
          <legend className="text-xs font-medium text-text">
            {t("ticketing", "sectorsServed")}
          </legend>
          <p className="mt-1 text-xs text-text-secondary">
            {t("ticketing", "sectorsServedHint")}
          </p>
          <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
            {sections.map((section) => (
              <li key={section.id}>
                <label className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface-2">
                  <input
                    type="checkbox"
                    checked={chosen.includes(section.id)}
                    onChange={() => toggle(section.id)}
                    className="size-4 rounded border-border"
                  />
                  <span className="text-text-secondary">{section.name}</span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      </div>
    </Dialog>
  );
}

function SeatsDialog({
  open,
  onOpenChange,
  onSubmit,
  busy,
  section,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (plan: Record<string, unknown>) => void;
  busy: boolean;
  section?: LayoutSection;
}) {
  const { t } = useI18n();
  const [rows, setRows] = useState("10");
  const [seats, setSeats] = useState("20");
  const [startLabel, setStartLabel] = useState("A");
  const [firstNumber, setFirstNumber] = useState("1");
  const [style, setStyle] = useState("ALPHABETIC");
  const [direction, setDirection] = useState("LEFT_TO_RIGHT");
  const [wheelchair, setWheelchair] = useState("");
  const [obstructed, setObstructed] = useState("");

  const existing = (section?.rows.length ?? 0) > 0;
  const list = (value: string) =>
    value
      .split(",")
      .map((entry) => entry.trim().toUpperCase())
      .filter(Boolean);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("ticketing", "generateSeats")}
      description={section?.name}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            variant={existing ? "danger" : "primary"}
            loading={busy}
            onClick={() =>
              onSubmit({
                row_count: Number(rows) || 1,
                seats_per_row: Number(seats) || 1,
                row_start_label: startLabel || "A",
                row_label_style: style,
                first_seat_number: Number(firstNumber) || 1,
                direction,
                wheelchair_seats: list(wheelchair),
                obstructed_seats: list(obstructed),
                // Regenerating destroys what is there, so it is the caller
                // that says so — and the button turns red when it will.
                replace: existing,
              })
            }
          >
            {existing ? t("ticketing", "regenerate") : t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {existing && (
          <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
            {t("ticketing", "regenerateWarning")}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ticketing", "rowCount")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={1}
                max={200}
                value={rows}
                onChange={(e) => setRows(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("ticketing", "seatsPerRow")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={1}
                max={200}
                value={seats}
                onChange={(e) => setSeats(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("ticketing", "rowStart")}>
            {(props) => (
              <Input
                {...props}
                value={startLabel}
                onChange={(e) => setStartLabel(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("ticketing", "firstSeatNumber")}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0}
                value={firstNumber}
                onChange={(e) => setFirstNumber(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("ticketing", "rowLabels")}>
            {() => (
              <Select
                value={style}
                onChange={setStyle}
                options={[
                  { value: "ALPHABETIC", label: "A, B, C…" },
                  { value: "NUMERIC", label: "1, 2, 3…" },
                ]}
              />
            )}
          </Field>
          <Field label={t("ticketing", "numbering")}>
            {() => (
              <Select
                value={direction}
                onChange={setDirection}
                options={[
                  { value: "LEFT_TO_RIGHT", label: t("ticketing", "leftToRight") },
                  { value: "RIGHT_TO_LEFT", label: t("ticketing", "rightToLeft") },
                ]}
              />
            )}
          </Field>
        </div>

        <Field
          label={t("ticketing", "wheelchairSeats")}
          help={t("ticketing", "seatAddressHint")}
        >
          {(props) => (
            <Input
              {...props}
              value={wheelchair}
              placeholder="A:1, A:2"
              onChange={(e) => setWheelchair(e.target.value)}
            />
          )}
        </Field>
        <Field
          label={t("ticketing", "obstructedSeats")}
          help={t("ticketing", "seatAddressHint")}
        >
          {(props) => (
            <Input
              {...props}
              value={obstructed}
              placeholder="A:1, A:22"
              onChange={(e) => setObstructed(e.target.value)}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}
