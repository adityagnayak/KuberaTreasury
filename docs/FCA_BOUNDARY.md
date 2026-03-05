# FCA Authorisation Boundary — KuberaTreasury v1

## Position

KuberaTreasury v1 does not require authorisation under the Payment
Services Regulations 2017 (PSR 2017).

## Basis

KuberaTreasury generates ISO 20022 PAIN.001 XML files which are
downloaded by the user and uploaded manually to their bank. The
system does not initiate, transmit, or execute payment orders on
behalf of users through direct bank connectivity.

This activity does not constitute a Payment Initiation Service
under PSR 2017 Schedule 1 Part 1. No FCA authorisation or
registration is therefore required for this functionality.

## Scope Boundary

Direct API-based payment initiation (connecting to bank APIs to
submit payments in KuberaTreasury's name) is explicitly out of
scope for v1. Any future version introducing this capability must
obtain FCA authorisation before release.

## Review Date

This assessment must be reviewed before any v2 feature that
introduces direct bank connectivity.
