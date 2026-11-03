-- Temps en mouvement et distance par tranche de pente de 2 % (grade.py), en JSON :
-- [[borne basse en %, secondes, mètres], ...], pour l'allure en descente et le modèle allure-pente.
ALTER TABLE activity_metrics ADD COLUMN grade_bins TEXT;
