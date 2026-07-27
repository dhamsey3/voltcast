# AWS MLOps Predictive Maintenance

An end-to-end MLOps project on AWS for training, registering, deploying, and monitoring a predictive maintenance machine learning model.

## Goal

Build a production-style ML platform that demonstrates the full machine learning lifecycle:

**Data → Preprocessing → Training → Evaluation → Model Registry → Approval → Deployment → Monitoring**

The focus of this project is not only model accuracy, but also infrastructure automation, reproducibility, security, CI/CD, model versioning, and monitoring.

## Planned Architecture

```text
GitHub
  |
  | CI/CD
  v
Terraform
  |
  v
AWS Infrastructure
  |
  +--> S3
  |     |
  |     +--> raw/
  |     +--> processed/
  |     +--> model-artifacts/
  |
  +--> SageMaker Processing
  |
  +--> SageMaker Training
  |
  +--> SageMaker Model Registry
  |       |
  |       +--> Model v1
  |       +--> Model v2
  |       +--> Model v3
  |
  +--> SageMaker Endpoint
  |
  +--> SageMaker Model Monitor
  |
  +--> CloudWatch
```

## Project Objectives

### 1. Infrastructure with Terraform

Provision the AWS infrastructure using Terraform.

Resources should include:

* S3 buckets or prefixes for raw data, processed data, and model artifacts
* SageMaker IAM roles
* SageMaker resources
* ECR repository if a custom training or inference container is used
* CloudWatch monitoring
* KMS encryption where appropriate
* Networking and VPC configuration if required

Use least-privilege IAM policies.

---

### 2. Dataset

Use a public predictive-maintenance or equipment-failure dataset.

Example problem:

> Predict whether a machine is likely to fail based on sensor measurements such as temperature, pressure, rotational speed, vibration, or equipment usage.

Store the original dataset in:

```text
s3://<bucket>/raw/
```

Processed data should be stored separately:

```text
s3://<bucket>/processed/
```

---

### 3. Data Processing

Use SageMaker Processing to:

* clean the dataset
* handle missing values
* encode categorical variables
* create features
* split data into training, validation, and test sets
* upload processed datasets to S3

Processing code should live under:

```text
src/preprocessing/
```

---

### 4. Model Training

Train a classification model using SageMaker.

Possible algorithms:

* XGBoost
* Random Forest
* LightGBM
* Logistic Regression

Start simple.

The training job should:

* read training data from S3
* train the model
* calculate relevant metrics
* save the model artifact to S3

Possible metrics:

* precision
* recall
* F1 score
* ROC-AUC

---

### 5. Experiment Tracking

Initially use SageMaker experiments or training-job metadata.

Later add MLflow to track:

* parameters
* metrics
* experiments
* artifacts
* model runs

---

### 6. Model Evaluation

Create an evaluation step after training.

The pipeline should determine whether the candidate model meets an agreed threshold.

Example:

```text
F1 >= 0.85
```

If the model does not meet the threshold:

```text
Training
   |
Evaluation
   |
   +--> FAIL --> Stop
```

If it passes:

```text
Training
   |
Evaluation
   |
   +--> PASS --> Model Registry
```

---

### 7. SageMaker Model Registry

Create a model package group such as:

```text
PredictiveMaintenanceModel
```

Register successful models as different versions.

Example:

```text
PredictiveMaintenanceModel

Version 1
  F1: 0.81
  Status: Rejected

Version 2
  F1: 0.87
  Status: Approved

Version 3
  F1: 0.89
  Status: PendingManualApproval
```

Store model metadata and evaluation metrics with each model version.

---

### 8. Model Approval

Use a model approval workflow.

Models should initially be registered as:

```text
PendingManualApproval
```

Only approved models should be eligible for production deployment.

---

### 9. Model Deployment

Deploy an approved model to a SageMaker endpoint.

Create an inference API that accepts sensor values and returns something similar to:

```json
{
  "failure_probability": 0.87,
  "prediction": "failure"
}
```

Containerise custom inference code with Docker if needed.

---

### 10. CI/CD

Use GitHub Actions.

Create separate workflows for:

```text
terraform.yml
training.yml
deployment.yml
```

The pipeline should eventually support:

```text
Git Push
   |
Tests
   |
Terraform Validate
   |
Build
   |
Train
   |
Evaluate
   |
Register Model
   |
Approve Model
   |
Deploy
```

Production deployment should require an approved model.

---

### 11. Testing

Add automated tests for:

* preprocessing
* feature transformations
* training code
* inference
* Terraform
* API input validation

Suggested structure:

```text
tests/
├── test_preprocessing.py
├── test_training.py
└── test_inference.py
```

---

### 12. Model Monitoring

Enable SageMaker Model Monitor.

Monitor:

* input-data distribution
* prediction distribution
* model quality
* endpoint latency
* endpoint errors
* data drift

Use CloudWatch for infrastructure and application metrics.

---

### 13. Drift Simulation

Generate synthetic production data that differs from the training distribution.

Example:

```text
Training

temperature mean: 70
vibration mean:   0.30
```

Later:

```text
Production

temperature mean: 92
vibration mean:   0.65
```

Use this to demonstrate how model monitoring detects drift.

---

### 14. Security

Implement:

* least-privilege IAM
* encrypted S3 storage
* KMS where appropriate
* restricted access to training datasets
* separate SageMaker execution roles
* private networking where practical

Possible roles:

```text
SageMakerProcessingRole
SageMakerTrainingRole
SageMakerInferenceRole
```

Each role should only have access to the resources it requires.

---

## Repository Structure

```text
aws-mlops-predictive-maintenance/
│
├── infrastructure/
│   ├── modules/
│   │   ├── iam/
│   │   ├── s3/
│   │   ├── sagemaker/
│   │   └── monitoring/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
│
├── src/
│   ├── preprocessing/
│   ├── training/
│   ├── evaluation/
│   └── inference/
│
├── pipelines/
│   └── sagemaker_pipeline.py
│
├── docker/
│   └── Dockerfile
│
├── tests/
│
├── scripts/
│
├── .github/
│   └── workflows/
│       ├── terraform.yml
│       ├── training.yml
│       └── deployment.yml
│
├── requirements.txt
├── Makefile
└── README.md
```

## Implementation Phases

### Phase 1 — Basic ML

* choose dataset
* perform exploratory analysis
* create preprocessing pipeline
* train baseline model locally
* evaluate model

### Phase 2 — AWS Training

* upload data to S3
* provision IAM with Terraform
* run SageMaker Processing
* run SageMaker Training
* store model artifacts in S3

### Phase 3 — MLOps Pipeline

* create SageMaker Pipeline
* add evaluation step
* register successful models
* implement Model Registry
* implement model approval

### Phase 4 — Deployment

* create inference code
* deploy approved model
* expose SageMaker endpoint
* test predictions

### Phase 5 — CI/CD

* automate testing
* automate Terraform validation
* automate training
* automate model registration
* automate deployment

### Phase 6 — Monitoring

* enable SageMaker Model Monitor
* configure CloudWatch
* simulate drift
* create alerts

### Phase 7 — Improvements

Possible later additions:

* MLflow
* EKS-based inference
* blue/green deployment
* canary deployment
* automated retraining
* EventBridge triggers
* Step Functions
* feature store
* multiple environments: dev/staging/prod
* cost monitoring

## Skills Demonstrated

This project should demonstrate experience with:

* AWS
* Amazon SageMaker
* SageMaker Model Registry
* SageMaker Pipelines
* SageMaker Model Monitor
* Amazon S3
* Amazon ECR
* IAM
* CloudWatch
* Terraform
* Python
* Docker
* GitHub Actions
* CI/CD
* ML model training
* ML model deployment
* model versioning
* model monitoring
* data drift
* MLOps architecture

## Final Goal

The final project should make it possible to explain the following in an interview:

> I built an end-to-end MLOps platform on AWS using Terraform, SageMaker, Python, Docker, and CI/CD. The system processes training data, trains and evaluates models, registers model versions in SageMaker Model Registry, requires approval before deployment, deploys approved models to SageMaker endpoints, and monitors the deployed model for operational issues and data drift.
