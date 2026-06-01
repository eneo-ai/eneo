import {
  Archive,
  Bell,
  BookOpen,
  Bot,
  Brain,
  Briefcase,
  BriefcaseBusiness,
  Building,
  Calendar,
  ChartColumn,
  ChartPie,
  CircleCheck,
  ClipboardCheck,
  ClipboardList,
  Clock,
  Code,
  CreditCard,
  Database,
  DollarSign,
  Eye,
  Factory,
  FileAudio,
  FileChartColumn,
  FileCheck,
  FileJson,
  FileSpreadsheet,
  FileText,
  FileUp,
  FolderOpen,
  Globe,
  GraduationCap,
  Handshake,
  Heart,
  House,
  Image,
  Key,
  Landmark,
  Layers,
  Lightbulb,
  ListChecks,
  Lock,
  Mail,
  MapPin,
  Megaphone,
  MessageSquare,
  Music,
  Newspaper,
  Package,
  Rocket,
  Scale,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Star,
  Stethoscope,
  Truck,
  User,
  Users,
  Video,
  Workflow,
  Wrench,
  Zap
} from "lucide-svelte";

type TemplateIconComponent = typeof Rocket;

type TemplateIconDefinition = {
  name: string;
  value: string;
  component: TemplateIconComponent;
};

const templateIconDefinitions = [
  { name: "Rocket", value: "rocket", component: Rocket },
  { name: "Sparkles", value: "sparkles", component: Sparkles },
  { name: "Zap", value: "zap", component: Zap },
  { name: "Star", value: "star", component: Star },
  { name: "Heart", value: "heart", component: Heart },
  { name: "Message Square", value: "message-square", component: MessageSquare },
  { name: "Mail", value: "mail", component: Mail },
  { name: "Bell", value: "bell", component: Bell },
  { name: "Calendar", value: "calendar", component: Calendar },
  { name: "Clock", value: "clock", component: Clock },
  { name: "User", value: "user", component: User },
  { name: "Users", value: "users", component: Users },
  { name: "Building", value: "building", component: Building },
  { name: "Home", value: "home", component: House },
  { name: "Briefcase", value: "briefcase", component: Briefcase },
  { name: "Business", value: "briefcase-business", component: BriefcaseBusiness },
  { name: "Shopping Cart", value: "shopping-cart", component: ShoppingCart },
  { name: "Credit Card", value: "credit-card", component: CreditCard },
  { name: "Dollar Sign", value: "dollar-sign", component: DollarSign },
  { name: "File Text", value: "file-text", component: FileText },
  { name: "File Upload", value: "file-up", component: FileUp },
  { name: "File Check", value: "file-check", component: FileCheck },
  { name: "File JSON", value: "file-json", component: FileJson },
  { name: "File Audio", value: "file-audio", component: FileAudio },
  { name: "File Spreadsheet", value: "file-spreadsheet", component: FileSpreadsheet },
  { name: "File Chart", value: "file-chart-column", component: FileChartColumn },
  { name: "Folder", value: "folder-open", component: FolderOpen },
  { name: "Image", value: "image", component: Image },
  { name: "Video", value: "video", component: Video },
  { name: "Music", value: "music", component: Music },
  { name: "Code", value: "code", component: Code },
  { name: "Database", value: "database", component: Database },
  { name: "Book", value: "book-open", component: BookOpen },
  { name: "Search", value: "search", component: Search },
  { name: "Bot", value: "bot", component: Bot },
  { name: "Brain", value: "brain", component: Brain },
  { name: "Clipboard List", value: "clipboard-list", component: ClipboardList },
  { name: "Clipboard Check", value: "clipboard-check", component: ClipboardCheck },
  { name: "Checklist", value: "list-checks", component: ListChecks },
  { name: "Circle Check", value: "circle-check", component: CircleCheck },
  { name: "Chart Column", value: "chart-column", component: ChartColumn },
  { name: "Chart Pie", value: "chart-pie", component: ChartPie },
  { name: "Globe", value: "globe", component: Globe },
  { name: "Map Pin", value: "map-pin", component: MapPin },
  { name: "Landmark", value: "landmark", component: Landmark },
  { name: "Scale", value: "scale", component: Scale },
  { name: "Handshake", value: "handshake", component: Handshake },
  { name: "Wrench", value: "wrench", component: Wrench },
  { name: "Settings", value: "settings", component: Settings },
  { name: "Workflow", value: "workflow", component: Workflow },
  { name: "Package", value: "package", component: Package },
  { name: "Layers", value: "layers", component: Layers },
  { name: "Archive", value: "archive", component: Archive },
  { name: "Lock", value: "lock", component: Lock },
  { name: "Key", value: "key", component: Key },
  { name: "Shield", value: "shield", component: Shield },
  { name: "Shield Check", value: "shield-check", component: ShieldCheck },
  { name: "Eye", value: "eye", component: Eye },
  { name: "Lightbulb", value: "lightbulb", component: Lightbulb },
  { name: "Megaphone", value: "megaphone", component: Megaphone },
  { name: "Newspaper", value: "newspaper", component: Newspaper },
  { name: "Education", value: "graduation-cap", component: GraduationCap },
  { name: "Healthcare", value: "stethoscope", component: Stethoscope },
  { name: "Truck", value: "truck", component: Truck },
  { name: "Factory", value: "factory", component: Factory }
] as const satisfies readonly TemplateIconDefinition[];

export type TemplateIconName = (typeof templateIconDefinitions)[number]["value"];
export type TemplateIconOption = (typeof templateIconDefinitions)[number];
export type { TemplateIconComponent };

export const templateIconOptions: readonly TemplateIconOption[] = templateIconDefinitions;

const templateIconOptionByValue: ReadonlyMap<string, TemplateIconOption> = new Map(
  templateIconOptions.map((option) => [option.value, option])
);

export function normalizeTemplateIconName(iconName: string | null | undefined): string | null {
  const trimmed = iconName?.trim();
  if (!trimmed) return null;

  return trimmed
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
}

export function isTemplateIconName(value: string | null | undefined): value is TemplateIconName {
  return typeof value === "string" && templateIconOptionByValue.has(value);
}

export function getTemplateIconOption(
  iconName: string | null | undefined
): TemplateIconOption | null {
  const value = normalizeTemplateIconName(iconName);
  return isTemplateIconName(value) ? (templateIconOptionByValue.get(value) ?? null) : null;
}

export function getTemplateIconComponent(
  iconName: string | null | undefined
): TemplateIconComponent | null {
  return getTemplateIconOption(iconName)?.component ?? null;
}
