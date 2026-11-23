# Strata profiles

Strata profile JSON files are machine-specific: they contain absolute model, tokenizer, engine, and log paths. This repository does not publish the owner's local profile files. Recreate profiles from your own Strata-generated config and keep the model path unchanged.

Recorded profile capacities:

| Profile role | Context |
|---|---:|
| short/medium baseline | 32,768 tokens |
| long coding context | 131,072 tokens |
| DeepSeek near-full context | 262,144 tokens |

The numeric context must be supported by the installed model and engine. Start a profile by its local saved name and stop it before switching to another model. See the [Strata replication playbook](../docs/strata-replication.md#3-prepare-a-context-profile).
