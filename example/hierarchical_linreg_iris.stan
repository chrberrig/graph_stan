data {
    int<lower=0> N; //number of data
    int<lower=1> K; // number of species
    array[N] int<lower=1, upper=K> species; // species indicator for each data point
    vector[N] x; //covariates
    vector[N] y; //variates
}

parameters {
    // hyper-params
    real mu_alpha; 
    real mu_beta; 
    real<lower=0> sigma_alpha; // std for alpha
    real<lower=0> sigma_beta;  // std for beta

    // model-params
    vector[K] alpha;//intercept
    vector[K] beta; //slope
    real<lower=0> sigma; //scatter
}

model {
    // Hyper-priors
    mu_alpha ~ normal(0, 10);
    mu_beta ~ normal(0, 10);
    sigma_alpha ~ normal(0, 5);
    sigma_beta ~ normal(0, 5);

    // Priors
    alpha ~ normal(mu_alpha, sigma_alpha);
    beta ~ normal(mu_beta, sigma_beta);
    sigma ~ normal(0,1);
    
    // Likelihood
    for(i in 1:N){
        y[i] ~ normal(alpha[species[i]] + beta[species[i]]*x[i], sigma); 
    }
}

generated quantities {
    vector[N] y_sim; //simulated data from posterior
    
    for(i in 1:N){
	      y_sim[i] = normal_rng(alpha[species[i]] + beta[species[i]]*x[i], sigma);
    }
}
