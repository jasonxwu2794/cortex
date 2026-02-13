#!/usr/bin/env bash
# ============================================================================
# Step 4b: Tech Stack Preferences
# Ask the user about their primary language, frameworks, package manager,
# database, and other tech preferences.
# ============================================================================

wizard_header "4b" "Tech Stack" "Tell us about your tech preferences."

# --- Skip or Use Defaults ---
echo ""
QUICK_CHOICE="$(gum choose \
    "Skip — I'm not sure" \
    "Use recommended defaults" \
    "Customize manually")"

case "$QUICK_CHOICE" in
    "Skip"*)
        log_info "Skipping tech stack — you can configure this later"
        state_set "tech_stack.language" ""
        state_set "tech_stack.frameworks" ""
        state_set "tech_stack.package_manager" ""
        state_set "tech_stack.database" ""
        state_set "tech_stack.other" ""
        wizard_success "Tech stack skipped!"
        return 0 2>/dev/null || exit 0
        ;;
    "Use recommended"*)
        state_set "tech_stack.language" "python"
        state_set "tech_stack.frameworks" "FastAPI"
        state_set "tech_stack.package_manager" "pip"
        state_set "tech_stack.database" ""
        state_set "tech_stack.other" ""
        wizard_divider
        gum style --bold "Tech Stack Configuration (defaults):"
        echo "  Language:        python"
        echo "  Frameworks:      FastAPI"
        echo "  Package Manager: pip"
        echo "  Database:        (no preference)"
        wizard_success "Tech stack defaults applied!"
        return 0 2>/dev/null || exit 0
        ;;
esac

# --- Defaults ---
DEF_LANGUAGE="$(state_get 'tech_stack.language' '')"
DEF_FRAMEWORKS="$(state_get 'tech_stack.frameworks' '')"
DEF_PKG_MANAGER="$(state_get 'tech_stack.package_manager' '')"
DEF_DATABASE="$(state_get 'tech_stack.database' '')"
DEF_OTHER="$(state_get 'tech_stack.other' '')"

# --- Primary Language ---
echo ""
gum style --foreground 212 "What's your primary programming language?"
LANG_OPTS=(
    "Python"
    "TypeScript / JavaScript"
    "Rust"
    "Go"
    "Java / Kotlin"
    "Other"
)

LANG_CHOICE="$(gum choose "${LANG_OPTS[@]}")"
case "$LANG_CHOICE" in
    Python)                    LANGUAGE="python" ;;
    "TypeScript / JavaScript") LANGUAGE="typescript" ;;
    Rust)                      LANGUAGE="rust" ;;
    Go)                        LANGUAGE="go" ;;
    "Java / Kotlin")           LANGUAGE="java" ;;
    Other)
        LANGUAGE="$(wizard_input "🔧 Language:" "e.g. Ruby, C++, Elixir" "$DEF_LANGUAGE")"
        LANGUAGE="${LANGUAGE:-other}"
        ;;
esac

# --- Frameworks (multi-select based on language) ---
echo ""
gum style --foreground 212 "Select your preferred frameworks (space to select, enter to confirm):"

case "$LANGUAGE" in
    python)
        FW_OPTS=("FastAPI" "Django" "Flask" "PyTorch" "LangChain")
        ;;
    typescript)
        FW_OPTS=("Next.js" "React" "Express" "Nest.js" "Svelte")
        ;;
    rust)
        FW_OPTS=("Actix" "Axum" "Tokio")
        ;;
    go)
        FW_OPTS=("Gin" "Echo" "Fiber")
        ;;
    java)
        FW_OPTS=("Spring Boot" "Quarkus")
        ;;
    *)
        FW_OPTS=()
        ;;
esac

FRAMEWORKS=""
if [ ${#FW_OPTS[@]} -gt 0 ]; then
    FRAMEWORKS="$(gum choose --no-limit "${FW_OPTS[@]}" | tr '\n' ',' | sed 's/,$//')"
else
    FRAMEWORKS="$(wizard_input "🔧 Frameworks:" "e.g. Rails, Phoenix" "$DEF_FRAMEWORKS")"
fi

# --- Package Manager ---
echo ""
gum style --foreground 212 "Preferred package manager:"

case "$LANGUAGE" in
    python)
        PKG_OPTS=("pip" "poetry" "uv")
        ;;
    typescript)
        PKG_OPTS=("npm" "pnpm" "yarn" "bun")
        ;;
    *)
        PKG_OPTS=()
        ;;
esac

PKG_MANAGER=""
if [ ${#PKG_OPTS[@]} -gt 0 ]; then
    PKG_MANAGER="$(gum choose "${PKG_OPTS[@]}")"
else
    PKG_MANAGER="$(wizard_input "📦 Package manager:" "e.g. cargo, go modules" "$DEF_PKG_MANAGER")"
fi

# --- Database ---
echo ""
gum style --foreground 212 "Database preference:"
DB_OPTS=("No preference" "SQLite" "PostgreSQL" "MongoDB" "MySQL")
DATABASE="$(gum choose "${DB_OPTS[@]}")"

# --- Other Preferences ---
echo ""
gum style --foreground 240 "  Any other tech preferences? (optional)"
OTHER_PREFS="$(wizard_input "💡 Other:" "e.g. 'prefer functional style', 'always use Docker', 'test with pytest'" "$DEF_OTHER")"

# --- Save state ---
state_set "tech_stack.language" "$LANGUAGE"
state_set "tech_stack.frameworks" "$FRAMEWORKS"
state_set "tech_stack.package_manager" "$PKG_MANAGER"
state_set "tech_stack.database" "$DATABASE"
state_set "tech_stack.other" "$OTHER_PREFS"

# --- Summary ---
wizard_divider
gum style --bold "Tech Stack Configuration:"
echo "  Language:        $LANGUAGE"
echo "  Frameworks:      ${FRAMEWORKS:-none selected}"
echo "  Package Manager: ${PKG_MANAGER:-default}"
echo "  Database:        $DATABASE"
[ -n "$OTHER_PREFS" ] && echo "  Other:           $OTHER_PREFS"

wizard_success "Tech stack preferences saved!"
