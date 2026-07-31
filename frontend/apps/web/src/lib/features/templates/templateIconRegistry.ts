import Archive from "lucide-svelte/icons/archive";
import Bell from "lucide-svelte/icons/bell";
import BookOpen from "lucide-svelte/icons/book-open";
import Bot from "lucide-svelte/icons/bot";
import Brain from "lucide-svelte/icons/brain";
import Briefcase from "lucide-svelte/icons/briefcase";
import BriefcaseBusiness from "lucide-svelte/icons/briefcase-business";
import Building from "lucide-svelte/icons/building";
import Calendar from "lucide-svelte/icons/calendar";
import ChartColumn from "lucide-svelte/icons/chart-column";
import ChartPie from "lucide-svelte/icons/chart-pie";
import CircleCheck from "lucide-svelte/icons/circle-check";
import ClipboardCheck from "lucide-svelte/icons/clipboard-check";
import ClipboardList from "lucide-svelte/icons/clipboard-list";
import Clock from "lucide-svelte/icons/clock";
import Code from "lucide-svelte/icons/code";
import CreditCard from "lucide-svelte/icons/credit-card";
import Database from "lucide-svelte/icons/database";
import DollarSign from "lucide-svelte/icons/dollar-sign";
import Eye from "lucide-svelte/icons/eye";
import Factory from "lucide-svelte/icons/factory";
import FileAudio from "lucide-svelte/icons/file-audio";
import FileChartColumn from "lucide-svelte/icons/file-chart-column";
import FileCheck from "lucide-svelte/icons/file-check";
import FileJson from "lucide-svelte/icons/file-json";
import FileSpreadsheet from "lucide-svelte/icons/file-spreadsheet";
import FileText from "lucide-svelte/icons/file-text";
import FileUp from "lucide-svelte/icons/file-up";
import FolderOpen from "lucide-svelte/icons/folder-open";
import Globe from "lucide-svelte/icons/globe";
import GraduationCap from "lucide-svelte/icons/graduation-cap";
import Handshake from "lucide-svelte/icons/handshake";
import Heart from "lucide-svelte/icons/heart";
import House from "lucide-svelte/icons/house";
import Image from "lucide-svelte/icons/image";
import Key from "lucide-svelte/icons/key";
import Landmark from "lucide-svelte/icons/landmark";
import Layers from "lucide-svelte/icons/layers";
import Lightbulb from "lucide-svelte/icons/lightbulb";
import ListChecks from "lucide-svelte/icons/list-checks";
import Lock from "lucide-svelte/icons/lock";
import Mail from "lucide-svelte/icons/mail";
import MapPin from "lucide-svelte/icons/map-pin";
import Megaphone from "lucide-svelte/icons/megaphone";
import MessageSquare from "lucide-svelte/icons/message-square";
import Music from "lucide-svelte/icons/music";
import Newspaper from "lucide-svelte/icons/newspaper";
import Package from "lucide-svelte/icons/package";
import Rocket from "lucide-svelte/icons/rocket";
import Scale from "lucide-svelte/icons/scale";
import Search from "lucide-svelte/icons/search";
import Settings from "lucide-svelte/icons/settings";
import Shield from "lucide-svelte/icons/shield";
import ShieldCheck from "lucide-svelte/icons/shield-check";
import ShoppingCart from "lucide-svelte/icons/shopping-cart";
import Sparkles from "lucide-svelte/icons/sparkles";
import Star from "lucide-svelte/icons/star";
import Stethoscope from "lucide-svelte/icons/stethoscope";
import Truck from "lucide-svelte/icons/truck";
import User from "lucide-svelte/icons/user";
import Users from "lucide-svelte/icons/users";
import Video from "lucide-svelte/icons/video";
import Workflow from "lucide-svelte/icons/workflow";
import Wrench from "lucide-svelte/icons/wrench";
import Zap from "lucide-svelte/icons/zap";

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
