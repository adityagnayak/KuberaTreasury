# RBAC Permission Matrix (Explicit Deny > Explicit Allow > Default Deny)

## Actions Covered

1. tenant.manage
2. user.manage
3. role.manage
4. rbac.policy.manage
5. ledger.event.create
6. ledger.event.view
7. ledger.projection.view
8. payment.instruction.create
9. payment.instruction.approve
10. payment.instruction.export_pain001
11. payment.policy.manage
12. bank.account.manage
13. hmrc.obligation.view
14. hmrc.submission.create
15. hmrc.reference.manage
16. paye.calendar.manage
17. cir.review
18. intercompany.log.manage
19. personal_data.read
20. personal_data.erase
21. audit.view
22. audit.export_signed_pdf
23. security.ip_allowlist.manage
24. security.session.revoke
25. ai.inference.execute
26. ai.inference.audit.view
27. reporting.view

| Role | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| system_admin | A | A | A | A | A | A | A | A | A | A | A | A | A | A | A | A | A | A | D | D | A | A | A | A | A | A | A |
| cfo | D | D | D | D | D | A | A | A | A | A | A | A | A | A | A | A | A | A | D | D | A | A | D | D | A | A | A |
| head_of_treasury | D | D | D | D | A | A | A | A | A | A | A | A | A | A | A | A | A | A | D | D | A | A | D | D | A | A | A |
| treasury_manager | D | D | D | D | A | A | A | A | A | A | A | A | A | A | A | A | A | A | D | D | A | A | D | A | A | A | A |
| treasury_analyst | D | D | D | D | A | A | A | A | D | D | D | D | A | D | D | A | D | A | D | D | A | D | D | D | A | D | A |
| auditor | D | D | D | D | D | A | A | D | D | D | D | D | A | D | D | D | A | A | D | D | A | A | D | D | D | A | A |
| compliance_officer | D | D | D | A | D | A | A | D | D | D | D | D | A | A | A | A | A | A | A | A | A | A | A | A | D | A | A |
| board_member | D | D | D | D | D | D | A | D | D | D | D | D | A | D | D | D | A | D | D | D | A | D | D | D | D | D | A |

Legend: `A` = explicit allow, `D` = explicit deny.

## Enforcement Notes

- Permission resolution order is fixed: explicit deny, then explicit allow, else deny.
- Payment approval still requires DB four-eyes trigger checks even when action is allowed.
- `personal_data.erase` should be dual-control operationally (compliance + authorised officer) in Phase 2 workflows.
