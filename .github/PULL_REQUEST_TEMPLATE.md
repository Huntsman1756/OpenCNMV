## Summary

<!-- What changed and why. Link the gate / finding / issue if applicable. -->

## Checklist

- [ ] `python -B -m unittest discover -s tests -v` passes
- [ ] `python -m ruff check src tests` passes
- [ ] `python -m mypy src tests` passes
- [ ] No raw CNMV artefact bytes were modified or regenerated
- [ ] No gate manifest, fixture, or verdict was altered to make a check pass
- [ ] `docs/STATUS.md` updated if operational state changed
