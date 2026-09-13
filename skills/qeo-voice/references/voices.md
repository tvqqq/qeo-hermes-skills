# Qeo Voice Registry

## Chi Chi

- Slug: `chi-chi`
- Display name: `Chi Chi`
- Engine: VieNeu `v3turbo`
- Profile: `tight-denoised`
- Default: yes

Approved synthesis values:

```text
denoise=true
use_ref_codes=true
temperature=0.55
top_k=20
top_p=0.90
repetition_penalty=1.20
max_chars=140
silence_p=0.10
crossfade_p=0.0
```

The private `reference.wav` is not stored in Git. It is provisioned on the Mac mini under the configured Qeo Voice asset root.

To add a future voice, add a public registry entry and provision its private reference asset. Do not create a separate Hermes skill for each voice.
