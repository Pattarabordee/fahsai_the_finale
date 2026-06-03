# FahMai Product Docs

Read these files when treating FahMai as an enterprise product rather than a
one-off analysis project.

- `PRODUCT.md`: root product context, users, principles, and north star.
- `trusted_business_answer_engine.md`: capability contract for the core answer product.
- `enterprise_roadmap.md`: milestone roadmap from governed retrieval to enterprise workflows.
- `product_metrics.md`: product, reliability, performance, and governance metrics.
- `scripts/evaluate_product_readiness.py`: DB-backed readiness metrics command.

Recommended read order:

1. `PRODUCT.md`
2. `docs/product/trusted_business_answer_engine.md`
3. `docs/product/enterprise_roadmap.md`
4. `docs/product/product_metrics.md`

Readiness command:

```bash
python scripts/evaluate_product_readiness.py --pretty
```
