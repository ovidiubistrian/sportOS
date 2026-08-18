import type { Catalogue } from "@footbola/i18n";
import {
  BarChart3,
  Building2,
  CreditCard,
  LayoutDashboard,
  Mail,
  CalendarDays,
  LandPlot,
  Newspaper,
  ScanLine,
  Ticket,
  Palette,
  Shirt,
  ShoppingBag,
  Users,
  type LucideIcon,
} from "lucide-react";

/**
 * The navigation model.
 *
 * One definition, three consumers: the sidebar, the breadcrumb and the command
 * palette. Keeping it in a data file rather than in JSX is what stops those
 * three drifting out of step — which they always do when each builds its own
 * list.
 *
 * Paths are relative to the club: the shell and the palette prefix them with
 * the club slug from the URL. Storing them absolute here would mean every
 * consumer had to remember to strip and re-add it, which is exactly the kind
 * of detail that gets forgotten in one of the three.
 *
 * Every entry names the permission that gates it. Hiding an item the user
 * cannot use is a clarity decision; the route enforces it server-side either
 * way (see tests/permissions/test_matrix.py).
 */

export interface NavItem {
  to: string;
  /** Key into the `nav` section of the message catalogue. */
  labelKey: keyof Catalogue["nav"];
  descriptionKey?: keyof Catalogue["nav"];
  icon: LucideIcon;
  permission: string;
  /** Extra words the command palette matches on, in every language we ship. */
  keywords?: string[];
  end?: boolean;
}

export interface NavGroup {
  labelKey: keyof Catalogue["nav"];
  items: NavItem[];
}

export const NAVIGATION: NavGroup[] = [
  {
    labelKey: "groupClub",
    items: [
      {
        to: "/",
        labelKey: "dashboard",
        descriptionKey: "dashboardHint",
        icon: LayoutDashboard,
        permission: "clubs.club.read",
        end: true,
        keywords: ["overview", "home", "start", "panou", "acasa", "acasă"],
      },
      {
        to: "/teams",
        labelKey: "teams",
        descriptionKey: "teamsHint",
        icon: Shirt,
        permission: "teams.team.read",
        keywords: ["squad", "age group", "u15", "lot", "echipe", "grupa", "grupă"],
      },
      {
        to: "/matches",
        labelKey: "matches",
        descriptionKey: "matchesHint",
        icon: CalendarDays,
        // Its own permission, not the squad's. A match commentator brought in
        // for one afternoon gets the fixture list and nothing else.
        permission: "matches.match.read",
        keywords: [
          "fixtures", "results", "league", "table", "cup", "standings",
          "meciuri", "rezultate", "clasament", "campionat", "cupa", "cupă", "etapa", "etapă",
        ],
      },
      {
        to: "/players",
        labelKey: "players",
        descriptionKey: "playersHint",
        icon: Users,
        permission: "players.player.read",
        keywords: ["squad", "roster", "registration", "jucatori", "jucători", "legitimare"],
      },
    ],
  },
  {
    labelKey: "groupMatchday",
    items: [
      {
        to: "/stadium",
        labelKey: "stadium",
        descriptionKey: "stadiumHint",
        icon: LandPlot,
        permission: "ticketing.venue.read",
        keywords: [
          "stand", "sector", "seat", "gate", "capacity", "map",
          "stadion", "tribuna", "tribună", "sector", "loc", "poarta", "poartă", "harta", "hartă",
        ],
      },
      {
        to: "/tickets",
        labelKey: "tickets",
        descriptionKey: "ticketsHint",
        icon: Ticket,
        permission: "ticketing.event.read",
        keywords: [
          "ticket", "match", "price", "sale", "season", "allocation",
          "bilet", "meci", "pret", "preț", "vanzare", "vânzare", "abonament", "alocare",
        ],
      },
      {
        to: "/scanner",
        labelKey: "scanner",
        descriptionKey: "scannerHint",
        icon: ScanLine,
        permission: "ticketing.access.scan",
        keywords: [
          "scan", "gate", "turnstile", "entry", "qr", "validate",
          "scanare", "poarta", "poartă", "turnichet", "intrare", "validare", "acces",
        ],
      },
    ],
  },
  {
    labelKey: "groupWebsite",
    items: [
      {
        to: "/news",
        labelKey: "news",
        descriptionKey: "newsHint",
        icon: Newspaper,
        permission: "cms.content.read",
        keywords: ["article", "match report", "signing", "press", "stiri", "știri", "articol", "cronica", "cronică"],
      },
      {
        to: "/shop",
        labelKey: "shop",
        descriptionKey: "shopHint",
        icon: ShoppingBag,
        permission: "commerce.product.read",
        keywords: [
          "store", "merch", "product", "order", "scarf", "shirt", "stock",
          "magazin", "produs", "comanda", "comandă", "stoc", "fular", "tricou",
        ],
      },
      {
        to: "/marketing",
        labelKey: "marketing",
        descriptionKey: "marketingHint",
        icon: Mail,
        permission: "cms.content.read",
        keywords: [
          "email", "newsletter", "campaign", "offer", "subscribers",
          "campanie", "oferta", "ofertă", "abonati", "abonați", "scrisoare",
        ],
      },
      {
        to: "/analytics",
        labelKey: "analytics",
        descriptionKey: "analyticsHint",
        icon: BarChart3,
        permission: "clubs.club.read",
        keywords: [
          "traffic", "visitors", "statistics", "stats", "sessions", "funnel",
          "trafic", "vizitatori", "statistici", "analiza", "analiză",
        ],
      },
      {
        to: "/site",
        labelKey: "site",
        descriptionKey: "siteHint",
        icon: Palette,
        permission: "clubs.club.read",
        keywords: ["template", "colours", "colors", "brand", "domain", "theme", "culori", "sablon", "șablon", "domeniu", "design"],
      },
    ],
  },
  {
    labelKey: "groupOrganisation",
    items: [
      {
        to: "/staff",
        labelKey: "staff",
        descriptionKey: "staffHint",
        icon: Users,
        permission: "staff.profile.read",
        keywords: [
          "coach", "manager", "physio", "account", "invite", "role", "permission",
          "antrenor", "staff", "cont", "invitatie", "invitație", "rol", "drepturi",
        ],
      },
      {
        to: "/payments",
        labelKey: "payments",
        descriptionKey: "paymentsHint",
        icon: CreditCard,
        permission: "payments.settings.read",
        keywords: [
          "card", "bt", "ipay", "banca", "bancă", "gateway", "plati", "plăți",
          "payment", "online", "checkout",
        ],
      },
      {
        to: "/settings",
        labelKey: "settings",
        descriptionKey: "settingsHint",
        icon: Building2,
        permission: "clubs.club.read",
        keywords: ["tenant", "locale", "currency", "plan", "billing", "setari", "setări", "limba", "limbă", "abonament"],
      },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAVIGATION.flatMap((group) => group.items);

/** Longest matching path wins, so `/news/:id` resolves to the News entry. */
export function activeItem(pathname: string): NavItem | undefined {
  return ALL_NAV_ITEMS.filter(
    (item) => pathname === item.to || (item.to !== "/" && pathname.startsWith(`${item.to}/`)),
  ).sort((a, b) => b.to.length - a.to.length)[0];
}
