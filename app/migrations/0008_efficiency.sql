-- Efficiency Factor (vitesse en m/min / FC moyenne, en mouvement) et découplage cardiaque
-- (dérive de l'EF entre la 1re et la 2e moitié du temps en mouvement, sorties d'au moins 1 h).
ALTER TABLE activity_metrics ADD COLUMN ef REAL;
ALTER TABLE activity_metrics ADD COLUMN decoupling_pct REAL;
