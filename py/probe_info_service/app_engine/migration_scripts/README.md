# Probe Info Service Migration Scripts

This folder contains scripts to migrate existing stateful data.

The script name must follow the pattern `migration_script_<order>.py`,
where `<order>` is the index number for the migration script.  The module
must contain exactly one instance of `.migration_script_types.Migrator`.

The RPC `AdminService.RunMigrationScripts()` attempts to run all migration
scripts with `<order>` larger than the internal-cached incremental count in
order.  The RPC stops when either all migration scripts finish or a migration
fails.
