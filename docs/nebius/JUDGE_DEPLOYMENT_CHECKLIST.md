# Judge deployment checklist — operator gate

- [ ] exact candidate SHA reviewed
- [ ] public hosting destination approved by operator
- [ ] provider secret injection is server-side only
- [ ] fixture target enforced
- [ ] health/readiness labels validated
- [ ] hard rate/token/cost/risk/deadline caps verified
- [ ] restart/replay behavior tested
- [ ] no generic shell/write endpoint exposed
- [ ] private HAT plaintext absent
- [ ] rights/security/legal review closed
- [ ] judging availability responsibility assigned
- [ ] real public URL receipt captured

Until all boxes are independently verified:
R5_JUDGE_PACKAGE=PASS_LOCAL
PUBLIC_DEPLOYMENT_PERFORMED=NO
