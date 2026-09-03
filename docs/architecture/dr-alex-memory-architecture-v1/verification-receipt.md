# Verification receipt

## Baseline

- Dr. Alex commit: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- Agent-memory commit: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`
- Governing report SHA-256 values are pinned in `RUN-CONTRACT.md`.

## Baseline tests

| Repository | Command | Result |
|---|---|---|
| Dr. Alex | `uv run pytest -q` | Exit 0, 2 skipped, warnings only |
| agent-memory | `uv run --project tools/memctl pytest -q` | Exit 0, 1,601 passed, 3 skipped, 1 warning |
| agent-memory health | `uv run --project tools/memctl memctl --json doctor` | Exit 7, known unresolved baseline defect |

## V2 rc3 current candidate hashes

- `RUN-CONTRACT.md`: `a8ec61fac2cf36e185d6e643138953a9ab55b5b836281cdc7f3f7c67fd35f091`
- `ARCHITECTURE.md`: `21d2b8ad37da3f0462b6c0eff935ebe1b84ddc61c8e8197a5bec1e9ec8b1ddf5`
- `ARCHITECTURE.html`: `415111b60493a7d4736c2e6f0f41eac6e740554edc03791955c42a54d7a83452`
- `CHANGE-SPEC.md`: `76ef88200a090b3ccf63703fad8312a451777f2a158d97563b26fc75b50bd35f`
- `CHANGE-SPEC.html`: `6e584d00a41165c89fe4c6f4a61d5e0447fd3e1367a4b48cbb249eaddf38b6d7`

These hashes are locally rendered and structurally checked. They have **not** received a final independent PASS and cannot be promoted under the current frozen evidence contract.

## V3 frozen governing hashes

- `RUN-CONTRACT.md`: `2b6ee3db3bf29b3550869a8b2b83130932b8606b8bf1a240cbd683ccce53fc62`
- `GOVERNING-EVIDENCE-v3.md`: `ee2a8370ad9024bdb416d1660753d0d6f4623ef3ae7ebfab42c26f9f2a2f4296`
- `EVALUATOR-v3.md`: `e53fd42c28c609c8f36684df6d39a7932bf97b9f40b6bb911227303eccecd710`
- `RUN-CONTRACT-v2.md` rollback: `a8ec61fac2cf36e185d6e643138953a9ab55b5b836281cdc7f3f7c67fd35f091`

The user approved the content-free replacement baseline. The restricted narrative reports remain preserved but non-governing and must not be included in review packets.

## V3 RC4 candidate hashes

- `ARCHITECTURE.md`: `dee6e99119cce1b1703b640842f50d220b4913e9cace24bcf456a269c9a6a7e3`
- `CHANGE-SPEC.md`: `29f65682fcae6820bd1ff3dce0aaf78d5bee4b401e6e17f6991b45db44d414e7`
- Derived `ARCHITECTURE.html`: `a527de4f2042be5e6ac2b1ee8200b10d01bba982e703d8fea0ccb6ece65d95c5`
- Derived `CHANGE-SPEC.html`: `1ae7e1a5c7b5083547521ed20b013a6d260983c8013a311cfa8a90555ceda723`

Local structural verification passed: the three v3 governing hashes remain unchanged; all 63 frozen outcomes are present exactly once; eight additive RC4 regression cases are present; stale v2 activation tokens and the unused TUI compatibility flag are absent; `git diff --check` exits 0.

## V3 stall artifacts

- `V3-STALL-REPORT.md`: `685c97c286c212e962671d07cdce05f48a2fb349c72bd40ee81bdbe9664973fb`
- `V3-STALL-REPORT.html`: `7535ca4533b42c756e11f363228df094a3195a0116658d46a02230728aa3b097`

## V4 authorized repair candidate

- `RUN-CONTRACT.md`: `26feada532ba19977c72ba3b9de51b6f8b8848ab23784c1ec320e7b6fd25e59e`
- `GOVERNING-EVIDENCE-v3.md`: `ee2a8370ad9024bdb416d1660753d0d6f4623ef3ae7ebfab42c26f9f2a2f4296`
- `EVALUATOR-v3.md`: `e53fd42c28c609c8f36684df6d39a7932bf97b9f40b6bb911227303eccecd710`
- `ARCHITECTURE.md`: `15925fc24590bff42ec7bcdbd564e2af4ff337dc952b8c7869a4465e668b7a39`
- `CHANGE-SPEC.md`: `8c496f8af5c626deed5cedecf4eea5cbe40a6267ab026d2a63a92b18574ee5e9`
- Derived `ARCHITECTURE.html`: `a122f255a4db28599a2f9083314fcdac137c540c9b50dc98ba2df1a6390cc668`
- Derived `CHANGE-SPEC.html`: `c823de2aef3732285f8baedfc967c4f90d4bb244fb40c7c034f5e94416dec77e`

Local checks confirm consent-before-claim in both resume paths, per-step consent in both documents, live-session-only drain, writer-disabled lease clearing, repository-baseline budget wording, all 63 frozen outcomes, and all eight additive regressions.

## Current phase

**V5 EXACT-HASH PASS.** Codex, Grok, and a fresh-context delegated validator verified all five hashes and returned PASS with zero blockers and zero majors. The document gate is closed. Local tracer-bullet tickets may now be published, followed by test-first D1 and M1-A implementation in isolated worktrees.

No live configuration, clinical data, Telegram route, gateway, or activation changed.
