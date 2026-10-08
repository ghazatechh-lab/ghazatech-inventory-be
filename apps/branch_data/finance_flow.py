from __future__ import annotations

from rest_framework import serializers

from apps.branches.models import Branch
from apps.branch_data.context import set_active_branch_id
from apps.branch_data.physical import PHYSICAL_BRANCH_CODES, is_physical_branch, request_active_branch


def canonical_branch(value):
    if value is None:
        return None
    qs = Branch.objects.using('default').filter(is_active=True)
    code = str(getattr(value, 'branch_code', '') or '').strip().upper()
    if code:
        return qs.filter(branch_code__iexact=code).first()
    raw = getattr(value, 'pk', value)
    text = str(raw or '').strip()
    if text.isdigit():
        return qs.filter(pk=int(text)).first()
    return qs.filter(branch_code__iexact=text).first() if text else None


def requested_finance_target(request):
    active = request_active_branch(request)
    if is_physical_branch(active):
        return canonical_branch(active)
    raw = None
    try:
        raw = request.data.get('branch') or request.data.get('target_branch')
    except (AttributeError, TypeError):
        pass
    raw = raw or request.query_params.get('target_branch')
    branch = canonical_branch(raw)
    return branch if branch and str(branch.branch_code).upper() in PHYSICAL_BRANCH_CODES else None


def require_finance_target(request):
    branch = requested_finance_target(request)
    if branch is None:
        raise serializers.ValidationError({'branch': 'Select Branch 1 or Branch 2. Branch 3 is a combined interface and cannot own finance data.'})
    return branch


class FinanceBranchGuardMixin:
    finance_write_methods = {'POST', 'PUT', 'PATCH'}

    def initial(self, request, *args, **kwargs):
        if request.method.upper() in self.finance_write_methods:
            target = require_finance_target(request)
            set_active_branch_id(target.pk)
            try:
                data = request.data
                old_mutable = getattr(data, '_mutable', None)
                if old_mutable is not None:
                    data._mutable = True
                # Only inject branch when the payload/model uses it; serializers
                # that do not expose branch will ignore it at the view layer.
                data['branch'] = target.pk
                if old_mutable is not None:
                    data._mutable = old_mutable
            except Exception:
                pass
        else:
            raw = request.query_params.get('target_branch')
            branch = canonical_branch(raw)
            if is_physical_branch(branch):
                set_active_branch_id(branch.pk)
        return super().initial(request, *args, **kwargs)
