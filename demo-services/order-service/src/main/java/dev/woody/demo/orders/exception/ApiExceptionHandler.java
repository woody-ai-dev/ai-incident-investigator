package dev.woody.demo.orders.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import lombok.extern.slf4j.Slf4j;

@RestControllerAdvice 
@Slf4j 
public class ApiExceptionHandler {
    
    @ExceptionHandler(PaymentTimeoutException.class)
    public ProblemDetail handlePaymentTimeout(PaymentTimeoutException exc) {
        log.error(
            "Payment request timed out (simulated): order={}",
            exc.getOrderId()
        );

        var problem = ProblemDetail.forStatusAndDetail(
            HttpStatus.GATEWAY_TIMEOUT,
            "Simulated payment dependency timeout."
        );

        problem.setTitle("Payment timeout");
        problem.setProperty("code", "PAYMENT_TIMEOUT");
        problem.setProperty("orderId", exc.getOrderId());

        return problem;
    }
}