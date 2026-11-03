-- Allure ajustée à la pente (grade.py, formule de Minetti) en s/km, et portions stables d'une
-- minute (hr_speed.py) en JSON : [[vitesse ajustée m/s, FC moyenne], ...], pour la forme du jour.
ALTER TABLE activity_metrics ADD COLUMN gap_pace_s_km REAL;
ALTER TABLE activity_metrics ADD COLUMN steady_blocks TEXT;
