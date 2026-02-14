-- Auto-generate slug on INSERT if not provided
CREATE OR REPLACE FUNCTION generate_work_slug()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.slug IS NULL THEN
    SELECT LOWER(rt.code) || '-' || LOWER(REPLACE(NEW.number, '/', '-')) || '-' || NEW.year::text
    INTO NEW.slug
    FROM regulation_types rt
    WHERE rt.id = NEW.regulation_type_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_works_auto_slug
  BEFORE INSERT ON works
  FOR EACH ROW
  EXECUTE FUNCTION generate_work_slug();
