# ⚠️ CRITICAL: IQE Proprietary Files in Git History

**Date**: November 21, 2025
**Status**: 🚨 **ACTION REQUIRED** - Proprietary files committed to git history
**Severity**: HIGH

---

## 🔍 Issue Found

**PROBLEM**: IQE test configuration files (proprietary data from `iqe-cost-management-plugin`) were committed to git history and are currently tracked in the repository.

### Files Affected

The following proprietary files are **tracked in git** despite being in `.gitignore`:

```
config/ocp_report_0_template.yml
config/ocp_report_1.yml
config/ocp_report_2.yml
config/ocp_report_7.yml
config/ocp_report_advanced.yml
config/ocp_report_advanced_daily.yml
config/ocp_report_distro.yml
config/ocp_report_forecast_const.yml
config/ocp_report_forecast_outlier.yml
config/ocp_report_missing_items.yml
config/ocp_report_ros_0.yml
config/today_ocp_report_0.yml
config/today_ocp_report_1.yml
config/today_ocp_report_2.yml
config/today_ocp_report_multiple_nodes.yml
config/today_ocp_report_multiple_nodes_projects.yml
config/today_ocp_report_multiple_projects.yml
config/today_ocp_report_node.yml
config/today_ocp_report_tiers_0.yml
config/today_ocp_report_tiers_1.yml
```

**Total**: 20 proprietary IQE test files

### Git History

**Initial Commit** (8a788b6):
- 18 files committed in initial POC commit

**Subsequent Commits**:
- 602b2b4: Modified `config/ocp_report_1.yml`
- 3182276: Modified `config/ocp_report_1.yml`

**Current Status**:
- Files are in `.gitignore` (lines 45-46)
- But files are **still tracked** in git (added before .gitignore)
- **Repository is 32 commits ahead of origin/main**
- ⚠️ **If pushed to GitHub, these files WILL be exposed**

---

## 🚨 Why This Is Critical

1. **Proprietary Data**: These are IQE test configurations from Red Hat's internal testing framework
2. **Git History**: Even though they're in `.gitignore` now, they exist in git history
3. **Push Risk**: If the current branch is pushed to GitHub, all history goes with it
4. **Public Exposure**: Once pushed to a public repo, data is effectively public forever

---

## ✅ Solutions

### Option 1: Remove from Git History (RECOMMENDED)

**Remove files from all commits while preserving other work**:

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator

# Create a backup first
git branch backup-before-cleanup

# Remove the files from ALL commits
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch config/ocp_report_*.yml config/today_ocp_report_*.yml' \
  --prune-empty --tag-name-filter cat -- --all

# Force garbage collection to remove the files completely
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Verify they're gone from history
git log --all --oneline --name-only -- "config/ocp_report_*.yml" "config/today_ocp_report_*.yml"
# Should return empty

# Ensure .gitignore is tracking them
git status

# Push with force (if origin exists and you have permission)
# git push origin --force --all
# git push origin --force --tags
```

**Pros**:
- Cleanest solution
- Files completely removed from history
- Safe to push to GitHub after cleanup

**Cons**:
- Rewrites git history (force push required if already shared)
- Requires force push to update remote

### Option 2: Remove from Tracking (Keep in History)

**Remove from current branch but leave in history**:

```bash
# Remove from git tracking but keep local copies
git rm --cached config/ocp_report_*.yml config/today_ocp_report_*.yml

# Commit the removal
git commit -m "Remove proprietary IQE files from tracking

These files are from iqe-cost-management-plugin and should not be
in version control. They remain in .gitignore and local working directory."
```

**Pros**:
- Simple, no history rewrite
- Files remain in your working directory

**Cons**:
- ❌ **Files still in git history** (commits 8a788b6, 3182276, 602b2b4)
- ❌ **Not safe to push to GitHub** - history contains proprietary data
- Only prevents future tracking, doesn't fix past exposure

### Option 3: Start Fresh Repository (NUCLEAR OPTION)

**Create new repo without problematic history**:

```bash
# Create new repo
cd ..
git clone --depth 1 poc-parquet-aggregator poc-parquet-aggregator-clean
cd poc-parquet-aggregator-clean

# Remove proprietary files
rm config/ocp_report_*.yml config/today_ocp_report_*.yml

# Create fresh commit
git add -A
git commit -m "Initial commit: OCP Parquet Aggregator (cleaned)"

# Update remote
git remote set-url origin <new-github-url>
git push -u origin main
```

**Pros**:
- Guaranteed clean history
- No proprietary data anywhere in history

**Cons**:
- Loses all commit history (32 commits)
- Loses all detailed change tracking
- Very disruptive

---

## 🎯 Recommended Action Plan

### Step 1: Verify Current State (DONE)

✅ Confirmed: 20 proprietary IQE files in git history
✅ Confirmed: Files tracked despite being in `.gitignore`
✅ Confirmed: 32 commits ahead of origin (not yet pushed)

### Step 2: Choose Solution

**RECOMMENDED**: **Option 1** (Remove from history)

**Why**:
- This is a local repo (32 commits ahead, no indication it's been shared)
- Clean history is critical for public GitHub repos
- Force push is acceptable if repo isn't widely shared

### Step 3: Execute Cleanup

```bash
# Backup current state
git branch backup-before-cleanup

# Remove proprietary files from all history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch config/ocp_report_*.yml config/today_ocp_report_*.yml config/ocp_poc_minimal.yml' \
  --prune-empty --tag-name-filter cat -- --all

# Clean up refs
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Verify cleanup
echo "Checking for remaining IQE files in history..."
git log --all --oneline --name-only -- "config/ocp_report_*.yml" "config/today_ocp_report_*.yml"

# If empty, cleanup successful!
echo "✅ Cleanup complete - safe to push to GitHub"
```

### Step 4: Prevent Future Issues

**Update `.gitignore`** (already done):
```gitignore
# IQE Test Configuration Files (PROPRIETARY)
config/ocp_report_*.yml
config/today_ocp_report_*.yml
config/ocp_poc_minimal.yml
```

**Add pre-commit hook** to prevent accidental commits:
```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# Prevent committing IQE proprietary files

IQE_FILES=$(git diff --cached --name-only | grep -E '(ocp_report_|today_ocp_report_)')

if [ -n "$IQE_FILES" ]; then
    echo "❌ ERROR: Attempting to commit proprietary IQE files:"
    echo "$IQE_FILES"
    echo ""
    echo "These files are from iqe-cost-management-plugin and cannot be committed."
    exit 1
fi
EOF

chmod +x .git/hooks/pre-commit
```

### Step 5: Safe to Push

After cleanup:
```bash
# Verify no proprietary files in history
git log --all --oneline --name-only -- "config/*.yml" | grep -E "(ocp_report|today_ocp)"
# Should return empty

# Push to GitHub (if remote configured)
git push origin main --force  # Force needed due to history rewrite

# Push feature branch
git push origin feature/ocp-in-aws-aggregation
```

---

## 📋 Verification Checklist

Before pushing to GitHub, verify:

- [ ] Run: `git ls-files "config/ocp_report_*.yml"` → Should return empty
- [ ] Run: `git ls-files "config/today_ocp_report_*.yml"` → Should return empty
- [ ] Run: `git log --all --name-only -- "config/ocp_report_*.yml"` → Should return empty
- [ ] Check: `.gitignore` includes IQE file patterns
- [ ] Check: Pre-commit hook installed and executable
- [ ] Test: Try to commit an IQE file → Should be blocked

---

## 🔒 Security Note

**If repository was already pushed to GitHub**:

1. **Immediately** make repository private (if public)
2. **Contact GitHub** to request cache clearance
3. **Rotate any secrets** that may have been in those files
4. **Notify security team** about potential data exposure

**Current Status**: Repository is 32 commits ahead of origin, so likely **NOT yet pushed** ✅

---

## ✅ Summary

**Issue**: 20 IQE proprietary test files committed to git history
**Risk**: HIGH - Would expose proprietary data if pushed to GitHub
**Status**: Detected before push (safe for now)
**Action**: Run Option 1 cleanup script to remove from history
**Timeline**: Execute immediately before any push to GitHub

---

**NEXT STEP**: Run the cleanup script from Option 1, then verify with the checklist above.

