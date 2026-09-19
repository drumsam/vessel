-- A separate, disposable database for the service tests, which drop its
-- public schema on every run. The development database is never touched.
CREATE DATABASE pricer_test OWNER pricer;
