# Card Guess Bot Development Rules

## Development workflow
- Small scoped changes only.
- Use TDD: RED -> GREEN -> full test suite.
- Run `git diff --check` before completion.
- Do not commit or push unless explicitly requested.
- Do not use `git add .`.

## Architecture
- Core game/statistics logic must remain independent from QQ.
- QQ layer only handles routing and presentation.
- Do not calculate statistics inside `qq/bot.py` or renderer.
- Runtime queries must consume local snapshots/assets and must not scan raw public run data.

## Data correctness
- Do not infer unavailable denominators.
- Do not label counts as rates without a valid denominator.
- Do not infer relic acquisition source from floor number.
- `relics_obtained` is incomplete and must not be treated as a universal acquisition log.
- Boss relic choice stats use `boss_relics`.
- Shop purchase data has purchase events but no offer denominator.
- Starter relics have no acquisition floor.

## Product language
- Player-facing QQ output should use natural player language, not internal metric names.
- Do not expose terms such as “终局”.
- Prefer useful interpretation over dumping fields.
- Do not display low-value statistics just because they exist.

## Player-facing statistics
- Default display answers the questions players actually care about:
  - Would I pick this when I encounter it?
  - Where does it rank among its peers?
  - Is there clear offer → pick / buy / choose decision data?
- Do not default to isolated percentages. If an ordinary player cannot tell whether a percentage is high or low without a reference point:
  - Prefer a peer ranking instead, e.g. “携带率第 31 / 36”.
  - Or hide it in the detailed data.
  - Do not force it on screen just to look “data-rich”.
- Display priority:
  a. Decision data:
     - card reward pick
     - boss relic choice
     - shop offer → purchase
     - event option choice
     - win delta (when a reasonable comparison cohort exists)
  b. Relative position among peers:
     - ranking within the same tier / character / act
  c. Raw percentage:
     - default display only when a user can directly understand its meaning
  d. Descriptive statistics:
     - acquisition floor
     - raw presence
     - Heart raw presence
     - not primary display by default unless there is clear product value
- Do not show a metric just because it is computable; it must answer a question a player would naturally ask.
- Rankings need a reasonable comparison cohort. For example:
  - relic: prefer the same decision context or source pool; use tier only as an explicitly justified fallback
  - card: compare within the same game + character + act
  Do not rank across naturally different distributions.
- Every ratio must use the correct denominator. Never use all characters as the denominator for character-specific entities. Do not infer character ownership from catalog color; use real data distributions / audited supported_roles.
- Default QQ output stays concise and conversational. Do not show:
  - internal schema field names
  - implementation terms such as denominator / sample_size
  - developer language such as “终局”
- Complex statistics may remain in the snapshot, but the default renderer may hide them.
- New entities (relic / potion / event / card) follow the same principle: first ask whether the data helps player decisions, then decide whether to show it.

Comparison and leaderboard rules:

- Never assume that entities are comparable only because they share the same tier, rarity, or broad type.
- Prefer a decision cohort: entities that compete in the same real player decision, with comparable opportunity cost and denominator.
- Comparison priority:
  1. same concrete decision context (same event / NPC / reward screen)
  2. same source pool and game stage
  3. broader source-specific cohort
  4. tier / rarity / character cohorts only as explicitly justified fallbacks
- Separate cohorts when game stage materially changes the decision. For example, Act 1 and Act 2 Boss relic choices should not be merged by default.
- Do not mix free rewards, shop purchases, event rewards, or unrelated NPC pools in one leaderboard merely because the entities have the same rarity.
- Every leaderboard must be able to answer: "Why are these entries fair to compare?"
- Prefer showing both the decision rate and its rank within the valid cohort when both are available.
- Leaderboards may support Top N, Bottom N, and full rankings only when the denominator and cohort are consistent.
- Low-sample entries must not create misleading rankings; define and test a minimum sample policy before exposing a leaderboard.

The unit of player-facing statistical value is often the decision context, not the entity itself.

## Player-facing localization

- All player-facing game terminology must use the official Simplified Chinese localization when an official translation exists.
- This includes relic names, card names, character names, NPC / Ancient names, event names, keywords, mechanics, locations, and other in-game terms.
- Do not invent, literally translate, or paraphrase an official game term from its English identifier.
- Internal English IDs, API field names, enum values, source keys, and NPC codes may remain in the data/model layer, but must not leak into player-facing QQ output.
- If an official Simplified Chinese translation cannot be verified, do not guess. Keep the unresolved localization explicit in the data/audit layer until a reliable official source is available.
- Bot-authored statistical explanations may use concise natural Chinese, but any embedded game terminology must still use the official localization.

## Scope discipline
- Do not expand a task into STS2, potion, event, or unrelated systems unless explicitly requested.
- Reuse existing card/relic infrastructure before creating parallel implementations.

## Testing
- Tests must use fictional or fixture data.
- Do not depend on real QQ messages or private user data.