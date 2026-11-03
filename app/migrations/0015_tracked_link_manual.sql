-- Sortie reliée ou déliée à la main : la liaison automatique ne revient plus dessus.
ALTER TABLE tracked_races ADD COLUMN link_manual INTEGER NOT NULL DEFAULT 0;
