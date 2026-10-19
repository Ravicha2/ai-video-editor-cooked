---
description: Someone downloaded the repo, opened Claude Code in it, and the editor plugin did not load.
max_turns: 6
plugins: []
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
append_system_prompt: |
  Eval dry run: this session has no shell tools, and that is expected; do not ask for them. Where a step runs a command, write the exact command in one line, then stop at the next question for the user. The working folder is a fresh download of the ai-video-editor-cooked repo, and no plugin from it is loaded. Its CLAUDE.md:

  # cooked.

  Most people who open this folder want to edit a video. When the user asks for an edit, drops a
  video, pastes a link, names a creator, or asks how to start:

  1. If the `ai-editor:start` skill is in your skill list, use it. It asks its own questions and runs
     setup, the creator breakdown, the cut and the styled edit in order.
  2. If it is not (the folder was not trusted, or this Claude Code is too old to load plugins from
     `.claude/settings.json`), ask in the question box (AskUserQuestion) whether to install the
     editor, recommended option first. On yes, run:
     `claude plugin marketplace add nextwork-projects/ai-video-editor-cooked` then
     `claude plugin install ai-editor@nextwork`. Then tell the user to type `/reload-plugins` and
     say "edit my video" again.

  If the user is changing this repo itself (skills, scripts, tests, docs), skip the above: follow
  `AGENTS.md`, `docs/BACKLOG.md` and the `improve` skill. To stop the plugins loading while you work
  on them, set them to `false` under `enabledPlugins` in `.claude/settings.local.json`.

  This fork is the user's personal work. Changes land on this repo's main and stop there: never
  open PRs or issues at `nextwork-projects/ai-video-editor-cooked`, and never bump plugin versions
  or push version tags; releases are nextwork's, and they didn't ask for a contribution. Work that
  needs tracking goes in this repo's own GitHub issues (the CapCut hand-off lives there, parent
  `Ravicha2/buddy-vdo#1`).
---
edit my video
