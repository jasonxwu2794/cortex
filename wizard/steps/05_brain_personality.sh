#!/usr/bin/env bash
# ============================================================================
# Step 5: Brain Agent Personality
# Customize the user-facing agent's name, style, verbosity, and personality.
# ============================================================================

wizard_header "5" "Brain Personality" "Customize your AI assistant's personality."

# --- Defaults ---
DEF_BRAIN_NAME="$(state_get 'brain.name' 'Brain')"
DEF_STYLE="$(state_get 'brain.style' '')"
DEF_VERBOSITY="$(state_get 'brain.verbosity' '')"
DEF_NOTES="$(state_get 'brain.personality_notes' '')"

if is_recommended; then
    [ -z "$DEF_STYLE" ] && DEF_STYLE="balanced"
    [ -z "$DEF_VERBOSITY" ] && DEF_VERBOSITY="adaptive"
fi

# --- Agent Name ---
BRAIN_NAME="$(wizard_input "🧠 Agent name:" "e.g. Brain, Atlas, Jarvis" "$DEF_BRAIN_NAME")"
BRAIN_NAME="${BRAIN_NAME:-Brain}"

# --- Communication Style ---
echo ""
gum style --foreground 212 "Communication style:"
STYLE_OPTS=("Casual — friendly, conversational, uses emoji" "Professional — formal, structured, concise" "Balanced — adapts to context (recommended)")

# Pre-select if available
STYLE_CHOICE="$(gum choose "${STYLE_OPTS[@]}")"
case "$STYLE_CHOICE" in
    Casual*)       STYLE="casual" ;;
    Professional*) STYLE="professional" ;;
    *)             STYLE="balanced" ;;
esac

# --- Verbosity ---
echo ""
gum style --foreground 212 "Verbosity level:"
VERB_OPTS=("Concise — short, to the point" "Detailed — thorough explanations" "Adaptive — matches the question complexity (recommended)")

VERB_CHOICE="$(gum choose "${VERB_OPTS[@]}")"
case "$VERB_CHOICE" in
    Concise*)  VERBOSITY="concise" ;;
    Detailed*) VERBOSITY="detailed" ;;
    *)         VERBOSITY="adaptive" ;;
esac

# --- Personality Notes ---
echo ""
gum style --foreground 240 "  Any personality notes? (optional — e.g. 'be witty', 'use humor', 'talk like a pirate')"
PERSONALITY_NOTES="$(wizard_input "✨ Personality:" "Press Enter to skip" "$DEF_NOTES")"

# --- Agent Transparency ---
echo ""
gum style --foreground 212 "Agent transparency:"
VERBOSE_OPTS=("Stealth — Brain handles everything silently, clean unified responses" "Verbose — Show when agents are working (🔬 Researcher is researching...)")

DEF_VERBOSE="$(state_get 'brain.verbose_mode' 'stealth')"
VERBOSE_CHOICE="$(gum choose "${VERBOSE_OPTS[@]}")"
case "$VERBOSE_CHOICE" in
    Verbose*) VERBOSE_MODE="verbose" ;;
    *)        VERBOSE_MODE="stealth" ;;
esac

# --- Save state ---
state_set "brain.name" "$BRAIN_NAME"
state_set "brain.style" "$STYLE"
state_set "brain.verbosity" "$VERBOSITY"
state_set "brain.personality_notes" "$PERSONALITY_NOTES"
state_set "brain.verbose_mode" "$VERBOSE_MODE"

# --- Summary ---
wizard_divider
gum style --bold "Brain Configuration:"
echo "  Name:        $BRAIN_NAME 🧠"
echo "  Style:       $STYLE"
echo "  Verbosity:   $VERBOSITY"
[ -n "$PERSONALITY_NOTES" ] && echo "  Personality: $PERSONALITY_NOTES"
echo "  Transparency: $VERBOSE_MODE"

wizard_success "Brain personality configured!"
