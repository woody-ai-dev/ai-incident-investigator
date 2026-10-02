package dev.woody.demo.orders.configuration.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import jakarta.validation.constraints.NotNull;

@Validated
@ConfigurationProperties(prefix = "demo")
public record DemoProperties(@NotNull PaymentMode paymentMode) {

    public enum PaymentMode {
        NORMAL,
        PAYMENT_TIMEOUT;
        
        public boolean isPaymentTimeout() {
            return this == PAYMENT_TIMEOUT;
        }
    }
}