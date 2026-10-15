import { Coffee, Compass, GraduationCap, Heart, Sparkles } from "lucide-react";

/**
 * One icon per archetype. Icons carry the meaning here - the app never uses
 * emoji, and the palette stays warm for every accent.
 */
const ICONS = {
  best_friend: Coffee,
  girlfriend: Heart,
  teacher: GraduationCap,
  mentor: Compass,
  custom: Sparkles,
};

export function personaIcon(personaId) {
  return ICONS[personaId] ?? Sparkles;
}

export default ICONS;
