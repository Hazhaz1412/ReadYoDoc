import sys

file_path = "frontend/src/routes/+page.svelte"

with open(file_path, "r") as f:
    lines = f.readlines()

# 1. Remove Realtime Sync and Ready Documents (Lines 513-530)
# We know the indices because they are 1-based in our view.
# 513 is index 512, 530 is index 529.
del lines[512:530]

# 2. We need to find the new lines for the next deletions since removing lines shifts everything.
# Let's do it from bottom to top to avoid index shifting.

with open(file_path, "r") as f:
    lines = f.readlines()

# Let's find the start of the `messages.length === 0` block
empty_start = -1
empty_end = -1
for i, line in enumerate(lines):
    if "{#if messages.length === 0}" in line:
        empty_start = i
    if empty_start != -1 and "            {/if}" in line and i > empty_start:
        empty_end = i
        break

new_empty_block = """            {#if messages.length === 0}
              <div class="my-10 flex flex-col items-center justify-center text-center">
                <div class="grid h-16 w-16 place-items-center rounded-3xl bg-[linear-gradient(135deg,rgba(100,210,255,0.15),rgba(255,186,102,0.15))] shadow-glow">
                  <svg class="h-8 w-8 text-sky-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M12 3L4 7.5v9L12 21l8-4.5v-9L12 3z"></path>
                    <path d="M4 7.5L12 12l8-4.5"></path>
                    <path d="M12 12v9"></path>
                  </svg>
                </div>
                <h2 class="mt-6 text-3xl font-extrabold tracking-tight text-white">How can I help you today?</h2>
                <p class="mt-3 max-w-xl text-slate-400">
                  I can search through your uploaded documents to find answers, summarize content, or extract key information.
                </p>

                <div class="mt-10 grid w-full max-w-3xl gap-3 sm:grid-cols-2 text-left">
                  {#each promptStarters as prompt}
                    <button
                      class="rounded-[20px] border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-slate-200 transition hover:-translate-y-0.5 hover:border-sky-300/30 hover:bg-sky-400/10"
                      type="button"
                      on:click={() => applyPrompt(prompt)}
                    >
                      {prompt}
                    </button>
                  {/each}
                </div>
              </div>
            {/if}
"""

if empty_start != -1 and empty_end != -1:
    lines[empty_start:empty_end+1] = [new_empty_block]


# Now remove the big header and stats blocks
# Start from `<header class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">`
header_start = -1
stats_end = -1

for i, line in enumerate(lines):
    if '<header class="flex flex-col gap-4' in line:
        header_start = i
    if header_start != -1 and '</section>' in line:
        # Check if the previous lines contain Prompt Starters
        if 'Prompt Starters' in "".join(lines[i-15:i]):
            stats_end = i
            break

if header_start != -1 and stats_end != -1:
    del lines[header_start:stats_end+1]


# Finally remove Realtime Sync
sync_start = -1
sync_end = -1
for i, line in enumerate(lines):
    if '<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-2">' in line:
        # Check if it has Realtime Sync
        if 'Realtime Sync' in lines[i+2]:
            sync_start = i
            sync_end = i + 17 # it is 18 lines long
            break

if sync_start != -1 and sync_end != -1:
    del lines[sync_start:sync_end+1]

with open(file_path, "w") as f:
    f.writelines(lines)

print("UI modifications applied.")
