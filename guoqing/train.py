import argparse
import os
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_squared_error
import numpy as np
from typing import Any
import json


def read_data(file_path ):
    """
    Reads data from a csv file.
    """
    return pd.read_csv(file_path)

def prepare_data(df):
    """
    Prepares data for training.
    """
    # identify feature columns
    feature_cols = [col for col in df.columns if 'feature_' in col]
    
    # convert feature columns to numeric, coercing errors
    for col in feature_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # fill missing values with 0, this is a simple strategy
    df.fillna(0, inplace=True)
    
    # create feature vectors
    X = df[feature_cols]
    y = df['target_value']
    
    return X, y

def train_model(X_train, y_train, params: dict[str, Any]):
    """
    Trains a lightgbm regression model.
    """
    # create dataset for lightgbm
    lgb_train = lgb.Dataset(X_train, y_train)
    
    print('Starting training...')
    # train model
    gbm = lgb.train(params,
                    lgb_train,
                    num_boost_round=100)
                    
    return gbm



def train_and_eval(item_no, df, X_train, y_train, params: dict[str, Any], metric_result_path):
    # train model
    model = train_model(X_train, y_train, params)
    
    # predict for all data
    feature_cols = [col for col in df.columns if 'feature_' in col]
    features = df[feature_cols]
    predictions = model.predict(features, num_iteration=model.best_iteration)
    df[f"{item_no}_predicted_value"] = predictions
    df.to_csv(f"data/{item_no}_predictions.csv", index=False)

    # calculate mse on train and test
    train_mse = mean_squared_error(df[df["is_train"] == 1]["target_value"], df[df["is_train"] == 1][f"{item_no}_predicted_value"])
    print(f"train mse: {train_mse:.4f}")

    test_mse = mean_squared_error(df[df["is_train"] == 0]["target_value"], df[df["is_train"] == 0][f"{item_no}_predicted_value"])
    print(f"test mse: {test_mse:.4f}")
    
    params_str = json.dumps({
        "max_depth": params["max_depth"],
        "n_estimators": params["n_estimators"],
        "feature_fraction": params["feature_fraction"],
        "learning_rate": params["learning_rate"],
    })
    with open(metric_result_path, "a") as f:
        f.write(f"{item_no},{params['max_depth']},{params['n_estimators']},{params['learning_rate']},{params['feature_fraction']},{train_mse:.4f},{test_mse:.4f}\n")

    # save model
    model_name = f"model_{item_no}.txt"
    model_path = os.path.join("models", model_name)
    os.makedirs("models", exist_ok=True)
    model.save_model(model_path)
    print(f"Model saved to {model_path}")


def main():
    """
    Main function to run the training pipeline.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, default="training_data.csv")
    parser.add_argument("--item_no", type=str, default="P4002")
    args = parser.parse_args()

    item_no = args.item_no
    # read data
    df = read_data(args.data_path)

    df = df[
        df[f"{item_no}_target_value"].notnull()
    ][
        ["Product Spec", "Adhesive_NART", "Liner_NART", "Backing_NART", f"{item_no}_lb", f"{item_no}_ub", f"{item_no}_target_value"] 
        + [col for col in df.columns if 'feature_' in col]
    ].copy()
    print(f"Total samples for item_no {item_no}: {len(df)}")
    df.rename(columns={f"{item_no}_target_value": "target_value"}, inplace=True)


    # shuffle records with fixed random seed for reproducibility
    df = df.sample(frac=1, random_state=0).reset_index(drop=True)

    # mark 10% as evaluation data
    test_size = int(0.15 * len(df))
    test_size = min(test_size, 10)
    df["is_train"] = 1
    df.loc[:test_size - 1, "is_train"] = 0

    # split data into training and evaluation sets based on the 'is_train' column
    train_df = df[df["is_train"] == 1]
    test_df = df[df["is_train"] != 1]

    print(f"Number of training samples: {len(train_df)}")
    print(f"Number of testing samples: {len(test_df)}")

    # prepare data
    X_train, y_train = prepare_data(train_df.copy())
    print(X_train.shape)


    X_test, y_test = prepare_data(test_df.copy())

    metric_result_path = f"data/{item_no}_train_metric.csv"
    with open(metric_result_path, 'w+') as f:
        f.write(f"item_no,max_depth,n_estimators,learning_rate,feature_fraction,train_mse,test_mse\n")

    for max_depth in [4]:
    # for max_depth in range(1, 5):
        for n_estimators in range(5, 17, 1):
            # for learning_rate in np.arange(0.05, 0.45, 0.05):
            for learning_rate in [0.05]:
                # specify your configurations as a dict
                params = {
                    'objective': 'regression',
                    'metric': 'mse',
                    'max_depth': max_depth,
                    'n_estimators': n_estimators,
                    'feature_fraction': 1,
                    'learning_rate': learning_rate,
                }
                train_and_eval(
                    item_no=item_no,
                    df=df,
                    X_train=X_train,
                    y_train=y_train,
                    params=params,
                    metric_result_path=metric_result_path,
                )
    


    

if __name__ == "__main__":
    main()
