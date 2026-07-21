# Issue Standards

Every issue opened in this repository must include the following information.
Issues missing required fields will be labelled `needs-more-info` and the reporter
will be asked to fill in the gaps.

## Required Fields by Issue Type

### Bug Reports
1. **Summary** - One-line description of the bug (Required)
2. **Steps to Reproduce** - Numbered steps from known-good state (Required)
3. **Expected Behavior** - What should happen (Required)
4. **Actual Behavior** - What actually happens, include errors (Required)
5. **Environment** - OS version, game version, tool version (Required)
6. **Screenshots / Logs** - Visual evidence (Recommended)
7. **Attempted Fixes** - What you already tried (Recommended)

### Feature Requests
1. **Summary** - One-line description (Required)
2. **Problem Statement** - What problem does this solve? (Required)
3. **Proposed Solution** - How should it work? (Required)
4. **Alternatives** - What else have you considered? (Recommended)

### Questions / Support
1. **Question** - What do you need help with? (Required)
2. **Context** - What have you already tried? (Required)
3. **Environment** - OS, game version, tool version (Required)

## Label Lifecycle

open -> standards check
  incomplete -> needs-more-info label + bot comment
    author replies -> re-check
      still incomplete -> reminder
      complete -> triaged label
  complete -> triaged label

## Label Reference

| Label | Meaning |
|-------|---------|
| needs-more-info | Missing required fields; waiting on author |
| triaged | Passed standards check; ready for review |
| auto-fix | Flagged for automated fix attempt |
| fix-in-progress | Auto-fix workflow actively working |
| fix-ready | PR opened, awaiting review |

## Auto-Fix Eligibility
1. Labelled `auto-fix` by maintainer OR bug with clear reproduction
2. Includes sufficient context (file paths, error messages, values)
3. Limited scope (single file, config toggle, offset update)

PRs from auto-fix require at least one reviewer approval before merge.
